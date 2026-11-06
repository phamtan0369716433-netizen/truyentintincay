import argparse
import socket
import sys

from utils import PacketHeader, compute_checksum

HDR_LEN = 16


class Kind:
    START = 0
    END = 1
    DATA = 2
    ACK = 3


def encode(kind, seq, payload=b""):
    # Đóng gói packet kèm theo checksum tính sẵn
    hdr = PacketHeader(type=kind, seq_num=seq, length=len(payload))
    hdr.checksum = 0
    hdr.checksum = compute_checksum(hdr / payload)
    return bytes(hdr / payload)


def decode(blob):
    # Giải mã data nhận về, check lại checksum xem có bị rớt/lỗi gì không
    if len(blob) < HDR_LEN:
        return None
    hdr = PacketHeader(blob[:HDR_LEN])
    payload = blob[HDR_LEN:HDR_LEN + hdr.length]
    if len(payload) < hdr.length:
        return None
    claimed = hdr.checksum
    hdr.checksum = 0
    if compute_checksum(hdr / payload) != claimed:
        return None
    return hdr.type, hdr.seq_num, payload


class StreamReceiver:
    def __init__(self, ip, port, window):
        self.window = window
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if hasattr(socket, "SIO_UDP_CONNRESET"):  # Fix lỗi connection reset trên Windows
            try:
                self.sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except OSError:
                pass
        self.sock.bind((ip, port))
        self.sink = sys.stdout.buffer

        self.active = False      # cờ kiểm tra đã bắt tay xong chưa
        self.next_seq = 0        # seq tiếp theo đang mong chờ nhận
        self.early = {}          # lưu tạm các gói đến trước hạn: seq -> payload

    # ---- helper methods ----
    def _reply(self, peer, ack_no):
        self.sock.sendto(encode(Kind.ACK, ack_no), peer)

    def _drain_in_order(self):
        # Lôi các gói đến liên tiếp từ bộ đệm tạm ra ghi thẳng ra output
        while self.next_seq in self.early:
            self.sink.write(self.early.pop(self.next_seq))
            self.next_seq += 1
        self.sink.flush()

    # ---- xử lý các loại gói tin đến ----
    def on_start(self, peer):
        if self.active:
            return
        self.active = True
        self.next_seq = 1
        self.early.clear()
        self._reply(peer, 1)

    def on_data(self, peer, seq, payload):
        if seq >= self.next_seq + self.window:
            return  # Vượt quá window cho phép thì lờ đi luôn, không thèm ACK
        if seq >= self.next_seq:
            self.early[seq] = payload
        self._drain_in_order()
        self._reply(peer, self.next_seq)

    def on_end(self, peer, seq):
        # Xử lý khi nhận gói END kết thúc phiên
        if seq != self.next_seq:
            self._reply(peer, self.next_seq)
            return False
        self.sink.flush()
        self._reply(peer, seq + 1)
        return True

    # ---- vòng lặp chính của receiver ----
    def run(self):
        finished = False
        while not finished:
            try:
                blob, peer = self.sock.recvfrom(2048)
            except OSError:
                continue

            pkt = decode(blob)
            if pkt is None:
                continue  # Lỗi checksum hoặc gói hỏng thì bỏ qua luôn
            kind, seq, payload = pkt

            if kind == Kind.START:
                self.on_start(peer)
            elif not self.active:
                continue
            elif kind == Kind.DATA:
                self.on_data(peer, seq, payload)
            elif kind == Kind.END:
                finished = self.on_end(peer, seq)

        self.sock.close()


def parse_args():
    ap = argparse.ArgumentParser(description="Reliable UDP receiver")
    ap.add_argument("receiver_ip", help="IP của máy chạy receiver")
    ap.add_argument("receiver_port", type=int, help="Cổng receiver lắng nghe")
    ap.add_argument("window_size", type=int, help="Kích thước cửa sổ nhận")
    return ap.parse_args()


if __name__ == "__main__":
    a = parse_args()
    StreamReceiver(a.receiver_ip, a.receiver_port, a.window_size).run()