import argparse
import select
import socket
import sys
import time

from utils import PacketHeader, compute_checksum

HDR_LEN = 16                       # 4 trường int x 4 byte (kích thước header chuẩn)
MAX_PKT = 1472                     # 1500 (MTU) - 20 (IP) - 8 (UDP)
MAX_PAYLOAD = MAX_PKT - HDR_LEN    # dung lượng payload tối đa trong một gói
RTO = 0.5                          # timeout chờ ACK: 0.5 giây


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


class SelectiveSender:
    def __init__(self, ip, port, window):
        self.window = window
        self.peer = (ip, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if hasattr(socket, "SIO_UDP_CONNRESET"):  # Fix lỗi connection reset trên Windows
            try:
                self.sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except OSError:
                pass
        self.frames = []     # danh sách các frame DATA đã được chuẩn bị sẵn (seq = index + 1)

    # ---- tiện ích ----
    def _load_frames(self):
        """Đọc toàn bộ dữ liệu từ stdin rồi băm nhỏ thành các cục vừa đủ gói."""
        raw = sys.stdin.buffer.read()
        for pos in range(0, len(raw), MAX_PAYLOAD):
            seq = len(self.frames) + 1
            self.frames.append(encode(Kind.DATA, seq, raw[pos:pos + MAX_PAYLOAD]))

    def _emit(self, frame):
        self.sock.sendto(frame, self.peer)

    def _wait_ack(self, limit):
        """Ngồi hóng ACK trong khoảng thời gian limit, quá hạn thì trả về None."""
        if limit <= 0:
            return None
        ready, _, _ = select.select([self.sock], [], [], limit)
        if not ready:
            return None
        try:
            blob, _ = self.sock.recvfrom(2048)
        except OSError:  # Windows đôi khi dính lỗi UDP connection reset
            return None
        pkt = decode(blob)
        if pkt is None or pkt[0] != Kind.ACK:
            return None
        return pkt[1]

    # ---- các giai đoạn của phiên truyền ----
    def handshake(self):
        """Bắt tay với bên nhận, gửi gói START liên tục tới khi nhận được ACK 1."""
        hello = encode(Kind.START, 0)
        while True:
            self._emit(hello)
            cutoff = time.time() + RTO
            while time.time() < cutoff:
                if self._wait_ack(cutoff - time.time()) == 1:
                    return

    def transfer(self):
        """Truyền dữ liệu bằng sliding window kết hợp Selective ACK (SACK)."""
        total = len(self.frames)
        oldest = 1              # gói cũ nhất trong window chưa được ACK
        upcoming = 1            # gói tiếp theo sẽ được tống đi
        confirmed = set()       # tập hợp lưu các seq trong window đã được ACK riêng lẻ
        clock = time.time()

        while oldest <= total:
            # Bơm đầy window nếu còn chỗ trống
            while upcoming < oldest + self.window and upcoming <= total:
                self._emit(self.frames[upcoming - 1])
                upcoming += 1

            left = RTO - (time.time() - clock)
            if left <= 0:
                # Hết giờ RTO: chỉ quăng lại những gói NÀO CHƯA ĐƯỢC ACK trong window
                for seq in range(oldest, upcoming):
                    if seq not in confirmed:
                        self._emit(self.frames[seq - 1])
                clock = time.time()
                continue

            ack = self._wait_ack(left)
            # Nhận được Selective ACK tương ứng với từng gói riêng lẻ
            if ack is not None and oldest <= ack < upcoming:
                confirmed.add(ack)
                prev_oldest = oldest
                while oldest in confirmed:  # Trượt cửa sổ qua các gói đã được xác nhận liên tiếp
                    confirmed.discard(oldest)
                    oldest += 1
                if oldest > prev_oldest:
                    clock = time.time()  # Dịch window thành công thì reset lại bộ đếm giờ

    def close_session(self):
        """Gửi gói END báo hết file, chờ ACK xác nhận đúng seq của gói END."""
        last = len(self.frames) + 1
        self._emit(encode(Kind.END, last))
        cutoff = time.time() + RTO
        while time.time() < cutoff:
            if self._wait_ack(cutoff - time.time()) == last:
                break

    def run(self):
        self._load_frames()
        self.handshake()
        self.transfer()
        self.close_session()
        self.sock.close()


def parse_args():
    ap = argparse.ArgumentParser(description="Reliable UDP sender (selective ACK)")
    ap.add_argument("receiver_ip", help="IP của máy chạy receiver")
    ap.add_argument("receiver_port", type=int, help="Cổng receiver lắng nghe")
    ap.add_argument("window_size", type=int, help="Kích thước cửa sổ truyền")
    return ap.parse_args()


if __name__ == "__main__":
    a = parse_args()
    SelectiveSender(a.receiver_ip, a.receiver_port, a.window_size).run()