import argparse
import random
import socket
import time

from scapy.all import IntField, Packet


class PacketHeader(Packet):
    name = "PacketHeader"
    fields_desc = [
        IntField("type", 0),
        IntField("seq_num", 0),
        IntField("length", 0),
        IntField("checksum", 0),
    ]


def get_seq_num(pkt):
    if len(pkt) > 1500:
        print("Error! Packet size exceeds 1500")
    pkt_header = PacketHeader(pkt[:16])
    pkt_type = "START/END"
    if pkt_header.type == 2:
        pkt_type = "DATA"
    elif pkt_header.type == 3:
        pkt_type = "ACK"
    return pkt_type, pkt_header.seq_num


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bind_addr", help="Binding address (sender address)")
    parser.add_argument("bind_port", type=int, help="Binding port (sender port)")
    parser.add_argument("receiver_addr", help="Receiver address")
    parser.add_argument("receiver_port", type=int, help="Receiver port")
    parser.add_argument(
        "error_types",
        help=(
            "String of error types to simulate (e.g. '0123' for all types). "
            "1: delay, 2: reorder, 3: drop, other: jam"
        ),
    )
    args = parser.parse_args()

    bind_addr = args.bind_addr
    bind_port = args.bind_port
    receiver_addr = args.receiver_addr
    receiver_port = args.receiver_port
    sender_addr = bind_addr
    sender_port = [0]  # Act like a pointer to 0 to allow modification
    options = args.error_types
    start_stage = 0

    def run(
        from_addr, from_port, from_socket, to_addr, to_port, to_socket, start_stage
    ):
        def delay():
            """Delay a packet by 0.4 seconds."""
            pkt, _ = from_socket.recvfrom(2048)
            pkt_type, seq_num = get_seq_num(pkt)
            print(f"Got it: Delay. {pkt_type}: {seq_num}")
            time.sleep(0.4)
            to_socket.sendto(pkt, (to_addr, to_port))

        def reorder():
            """Take in 6 packets, reorder them, and send them out."""
            num = 6
            packet_list = []

            for _ in range(num):
                try:
                    pkt, _ = from_socket.recvfrom(2048)
                    pkt_type, seq_num = get_seq_num(pkt)
                    print(f"Got it: Reorder. {pkt_type}: {seq_num}")
                    packet_list.append(pkt)
                except socket.error:
                    break

            random.shuffle(packet_list)
            for pkt in packet_list:
                to_socket.sendto(pkt, (to_addr, to_port))

        def drop():
            """Drop the next available packet."""
            pkt, _ = from_socket.recvfrom(2048)
            pkt_type, seq_num = get_seq_num(pkt)
            print(f"Got it: Drop. {pkt_type}: {seq_num}")

        def jam():
            """Randomly change a byte from the packet to "a"."""
            pkt, _ = from_socket.recvfrom(2048)
            i = random.randint(0, len(pkt) - 1)
            pkt = pkt[:i] + b"a" + pkt[i + 1 :]
            pkt_type, seq_num = get_seq_num(pkt)
            print(f"Got it: Jam. {pkt_type}: {seq_num}")
            to_socket.sendto(pkt, (to_addr, to_port))

        if start_stage < 10 or random.randint(1, 100) > 20:
            pkt, address = from_socket.recvfrom(2048, socket.MSG_DONTWAIT)
            if address[1] != receiver_port and address[1] != bind_port:
                sender_port.pop(0)
                sender_port.append(address[1])
            pkt_type, seq_num = get_seq_num(pkt)
            print(f"Got it: No messing. {pkt_type}: {seq_num}")
            to_socket.sendto(pkt, (to_addr, to_port))
        else:
            mode = int(options[random.randrange(len(options))])
            if mode == 1:
                delay()
            elif mode == 3:
                drop()
            elif mode == 2:
                reorder()
            else:
                jam()

    sender_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    sender_socket.settimeout(0.1)
    receiver_socket.settimeout(0.1)

    sender_socket.bind((bind_addr, bind_port))

    while True:
        # The proxy alternatively forwards messages from sender to receiver and from
        # receiver to sender; each turn transmits at most 5 packets
        try:
            for _ in range(5):
                run(
                    sender_addr,
                    sender_port,
                    sender_socket,
                    receiver_addr,
                    receiver_port,
                    receiver_socket,
                    start_stage,
                )
                start_stage += 1
        except socket.error:
            pass

        try:
            for _ in range(5):
                run(
                    receiver_addr,
                    receiver_port,
                    receiver_socket,
                    sender_addr,
                    sender_port[0],
                    sender_socket,
                    start_stage,
                )
                start_stage += 1
        except socket.error:
            pass


if __name__ == "__main__":
    main()
