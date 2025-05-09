"""
war card game client and server
"""
import asyncio
from collections import namedtuple
from enum import Enum
import logging
import random
import socket
import socketserver
import threading
import sys


"""
Namedtuples work like classes, but are much more lightweight so they end
up being faster. It would be a good idea to keep objects in each of these
for each game which contain the game's state, for instance things like the
socket, the cards given, the cards still available, etc.
"""
Game = namedtuple("Game", ["p1", "p2"])

# Stores the clients waiting to get connected to other clients
waiting_clients = []


class Command(Enum):
    """
    The byte values sent as the first byte of any message in the war protocol.
    """
    WANTGAME = 0
    GAMESTART = 1
    PLAYCARD = 2
    PLAYRESULT = 3


class Result(Enum):
    """
    The byte values sent as the payload byte of a PLAYRESULT message.
    """
    WIN = 0
    DRAW = 1
    LOSE = 2

def readexactly(sock, numbytes):
    """
    Accumulate exactly `numbytes` from `sock` and return those. If EOF is found
    before numbytes have been received, be sure to account for that here or in
    the caller.
    """
    acc = b"" #init empty byte string
    while len(acc) < numbytes:
        more = sock.recv(numbytes - len(acc))
        if not more:
            raise ConnectionError
        acc += more
    return acc


def kill_game(game):
    """
    TODO: If either client sends a bad message, immediately nuke the game.
    """
    logging.info("Ending game between %s and %s", game.p1, game.p2)
    game.p1.close()
    game.p2.close()


def compare_cards(card1, card2):
    """
    TODO: Given an integer card representation, return -1 for card1 < card2,
    0 for card1 = card2, and 1 for card1 > card2
    """
    if (card1 % 13) > (card2 % 13):
        return 1
    elif (card1 % 13) < (card2 % 13):
        return -1
    else:
        return 0
    

def deal_cards():
    """
    TODO: Randomize a deck of cards (list of ints 0..51), and return two
    26 card "hands."
    """
    deck = list(range(52))
    # shuffle cards
    for i in range(len(deck)):
        j = random.randint(i, len(deck) - 1)
        deck[i], deck[j] = deck[j], deck[i]
    
    p1_hand = deck[:26]
    p2_hand = deck[26:]
    return p1_hand, p2_hand
    

def serve_game(host, port):
    """
    TODO: Open a socket for listening for new connections on host:port, and
    perform the war protocol to serve a game of war between each client.
    This function should run forever, continually serving clients.
    """
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((host, port))
    server_socket.listen()

    waiting_clients = []

    while True:
        client_socket, client_address = server_socket.accept()
        logging.info("Client connected from %s", client_address)
        waiting_clients.append(client_socket)

        if len(waiting_clients) >= 2:
            client1_socket = waiting_clients.pop(0)
            client2_socket = waiting_clients.pop(0)

            logging.info("Starting game between two clients.")

            # Deal cards
            p1_hand, p2_hand = deal_cards()

            # Send GAMESTART messages
            client1_socket.send(bytes([Command.GAMESTART.value]) + bytes(p1_hand))
            client2_socket.send(bytes([Command.GAMESTART.value]) + bytes(p2_hand))

            logging.info("Game started, cards dealt")

            # Game loop: 26 rounds
            for round_num in range(26):
                card1 = client1_socket.recv(1)
                card2 = client2_socket.recv(1)

                if not card1 or not card2:
                    logging.error("Error receiving cards, closing game.")
                    kill_game(Game(client1_socket, client2_socket))
                    break

                result = compare_cards(card1[0], card2[0])

                client1_socket.send(bytes([Command.PLAYRESULT.value, result]))
                client2_socket.send(bytes([Command.PLAYRESULT.value, result]))

                logging.debug(
                    "Round %d: Client 1 card %d, Client 2 card %d, Result: %d",
                    round_num, card1[0], card2[0], result
                )

            else:
                client1_socket.close()
                client2_socket.close()

                logging.info("Game over.")
    

async def limit_client(host, port, loop, sem):
    """
    Limit the number of clients currently executing.
    You do not need to change this function.
    """
    async with sem:
        return await client(host, port, loop)

async def client(host, port, loop):
    """
    Run an individual client on a given event loop.
    You do not need to change this function.
    """
    try:
        reader, writer = await asyncio.open_connection(host, port)
        # send want game
        writer.write(b"\0\0")
        card_msg = await reader.readexactly(27)
        myscore = 0
        for card in card_msg[1:]:
            writer.write(bytes([Command.PLAYCARD.value, card]))
            result = await reader.readexactly(2)
            if result[1] == Result.WIN.value:
                myscore += 1
            elif result[1] == Result.LOSE.value:
                myscore -= 1
        if myscore > 0:
            result = "won"
        elif myscore < 0:
            result = "lost"
        else:
            result = "drew"
        logging.debug("Game complete, I %s", result)
        writer.close()
        return 1
    except ConnectionResetError:
        logging.error("ConnectionResetError")
        return 0
    except asyncio.streams.IncompleteReadError:
        logging.error("asyncio.streams.IncompleteReadError")
        return 0
    except OSError:
        logging.error("OSError")
        return 0

def main(args):
    """
    launch a client/server
    """
    host = args[1]
    port = int(args[2])
    if args[0] == "server":
        try:
            # your server should serve clients until the user presses ctrl+c
            serve_game(host, port)
        except KeyboardInterrupt:
            pass
        return
    else:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        
        asyncio.set_event_loop(loop)
        
    if args[0] == "client":
        loop.run_until_complete(client(host, port, loop))
    elif args[0] == "clients":
        sem = asyncio.Semaphore(1000)
        num_clients = int(args[3])
        clients = [limit_client(host, port, loop, sem)
                   for x in range(num_clients)]
        async def run_all_clients():
            """
            use `as_completed` to spawn all clients simultaneously
            and collect their results in arbitrary order.
            """
            completed_clients = 0
            for client_result in asyncio.as_completed(clients):
                completed_clients += await client_result
            return completed_clients
        res = loop.run_until_complete(
            asyncio.Task(run_all_clients(), loop=loop))
        logging.info("%d completed clients", res)

    loop.close()

if __name__ == "__main__":
    # Changing logging to DEBUG
    logging.basicConfig(level=logging.DEBUG)
    main(sys.argv[1:])
