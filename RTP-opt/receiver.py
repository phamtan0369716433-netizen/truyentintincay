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
    """Đóng gói packet kèm theo checksum tính sẵn."""
    hdr = PacketHeader(type=kind, seq_num=seq, length=len(payload))
    hdr.checksum = 0
    hdr.checksum = compute_checksum(hdr / payload)
    return bytes(hdr / payload)


def decode(blob):
    """Giải mã packet nhận về, check lại checksum xem có bị hỏng dữ liệu không."""
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


class SelectiveReceiver:
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

        self.active = False      # cờ kiểm tra phiên kết nối đã mở hay chưa
        self.next_seq = 0        # số thứ tự gói DATA tiếp theo cần ghi ra output
        self.early = {}          # lưu tạm các gói đến sớm trước hạn: seq -> payload

    # ---- tiện ích ----
    def _reply(self, peer, ack_no):
        self.sock.sendto(encode(Kind.ACK, ack_no), peer)

    def _drain_in_order(self):
        """Lôi các gói đến liên tiếp từ bộ đệm tạm ra ghi thẳng ra output stream."""
        while self.next_seq in self.early:
            self.sink.write(self.early.pop(self.next_seq))
            self.next_seq += 1
        self.sink.flush()

    # ---- xử lý từng loại gói tin ----
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
        # Phản hồi Selective ACK đúng chính xác cái seq vừa nhận được
        self._reply(peer, seq)

    def on_end(self, peer, seq):
        """Kiểm tra gói END xem khớp seq chưa để đóng phiên."""
        if seq != self.next_seq:
            return False  # Gói END chỉ hợp lệ khi đã nhận đủ sạch sẽ dữ liệu trước đó
        self.sink.flush()
        self._reply(peer, seq)
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
                continue  # Lỗi checksum hoặc gói hỏng thì vứt xó luôn
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
    ap = argparse.ArgumentParser(description="Reliable UDP receiver (selective ACK)")
    ap.add_argument("receiver_ip", help="IP của máy chạy receiver")
    ap.add_argument("receiver_port", type=int, help="Cổng receiver lắng nghe")
    ap.add_argument("window_size", type=int, help="Kích thước cửa sổ nhận")
    return ap.parse_args()


if __name__ == "__main__":
    a = parse_args()
    SelectiveReceiver(a.receiver_ip, a.receiver_port, a.window_size).run()