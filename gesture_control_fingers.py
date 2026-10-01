"""
ควบคุมมอเตอร์ด้วยท่ามือ (นับนิ้ว) ผ่านเว็บแคม ใช้ CV แบบเดียวกับไฟล์เดิม
ส่งคำสั่งได้ 2 ทาง: WiFi (UDP) หรือสาย USB (Serial)

ติดตั้งไลบรารี:
    pip install opencv-python mediapipe pyserial

วิธีรัน:
    python gesture_control_fingers.py --no-send --camera 1                 (ทดสอบท่ามืออย่างเดียว)
    python gesture_control_fingers.py --ip 192.168.1.50 --camera 1          (ส่งทาง WiFi)
    python gesture_control_fingers.py --port COM5 --camera 1                (ส่งทางสาย USB)

กด q ในหน้าต่างกล้องเพื่อออก
"""

import argparse
import math
import socket
import time
from collections import deque

import cv2
import mediapipe as mp

# ---------- ท่ามือ -> คำสั่ง ----------
# key = จำนวนนิ้วที่ชูขึ้น
GESTURES = {
    0: ("GRAB(fist)",         "K"),   # กำมือ      -> เบรก
    1: ("FORWARD (1 finger)",   "F"),   # ชู 1 นิ้ว  -> เดินหน้า
    2: ("BACKWARD (2 fingers)", "B"),   # ชู 2 นิ้ว  -> ถอยหลัง
    3: ("TURN LEFT (3)",        "L"),   # ชู 3 นิ้ว  -> เลี้ยวซ้าย
    4: ("TURN RIGHT (4)",       "R"),   # ชู 4 นิ้ว  -> เลี้ยวขวา
    5: ("RELEASE (open palm)",     "S"),   # แบมือ      -> หยุด
}
NO_HAND = ("NO HAND -> STOP", "S")      # ไม่เจอมือ -> หยุด (ปลอดภัยไว้ก่อน)

STABLE_FRAMES = 5      # ต้องเห็นท่าเดิมติดกันกี่เฟรมถึงจะเปลี่ยนคำสั่ง (กันกระตุก)
SEND_INTERVAL = 0.1    # ส่งคำสั่งซ้ำทุกกี่วินาที (ต้องน้อยกว่า TIMEOUT ฝั่งบอร์ด)


def dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def count_fingers(lm):
    """นับนิ้วที่ชูอยู่จาก landmark 21 จุดของ MediaPipe"""
    count = 0

    # นิ้วโป้ง: ปลายนิ้ว(4) ต้องอยู่ไกลจากโคนนิ้วก้อย(17) มากกว่าโคนโป้ง(2)
    if dist(lm[4], lm[17]) > dist(lm[2], lm[17]):
        count += 1

    # นิ้วชี้/กลาง/นาง/ก้อย: ปลายนิ้วต้องอยู่ไกลจากข้อมือ(0) มากกว่าข้อกลางนิ้ว
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        if dist(lm[tip], lm[0]) > dist(lm[pip], lm[0]):
            count += 1

    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", help="IP ของบอร์ด (ส่งทาง WiFi/UDP)")
    parser.add_argument("--udp-port", type=int, default=4210)
    parser.add_argument("--port", help="พอร์ต COM ของบอร์ด (ส่งทางสาย USB)")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--camera", type=int, default=0, help="หมายเลขกล้อง")
    parser.add_argument("--no-send", action="store_true",
                        help="ไม่ส่งคำสั่งไปบอร์ด (โหมดทดสอบ)")
    args = parser.parse_args()

    ser = None
    sock = None
    target = None

    if not args.no_send:
        if args.ip:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            target = (args.ip, args.udp_port)
            print(f"ส่งทาง WiFi ไปที่ {args.ip}:{args.udp_port}")
        elif args.port:
            import serial
            ser = serial.Serial(args.port, args.baud, timeout=0.1)
            time.sleep(2)  # รอ Arduino รีเซ็ตหลังเปิดพอร์ต
            print(f"ส่งทางสาย USB ที่ {args.port}")
        else:
            raise SystemExit("ต้องระบุ --ip (WiFi) หรือ --port (USB) หรือใช้ --no-send เพื่อทดสอบ")

    def send(cmd):
        if sock:
            try:
                sock.sendto(cmd.encode(), target)
            except OSError as e:
                print("ส่งไม่ได้:", e)
        elif ser:
            ser.write(cmd.encode())

    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise SystemExit("เปิดกล้องไม่ได้ ลองเปลี่ยน --camera")

    mp_hands = mp.solutions.hands
    mp_draw = mp.solutions.drawing_utils

    history = deque(maxlen=STABLE_FRAMES)
    stable = None          # None = ยังไม่เจอมือ
    last_send = 0.0

    with mp_hands.Hands(max_num_hands=1,
                        min_detection_confidence=0.7,
                        min_tracking_confidence=0.6) as hands:
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                frame = cv2.flip(frame, 1)  # กลับภาพเหมือนกระจก
                result = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

                raw = None
                if result.multi_hand_landmarks:
                    hand = result.multi_hand_landmarks[0]
                    raw = count_fingers(hand.landmark)
                    mp_draw.draw_landmarks(frame, hand, mp_hands.HAND_CONNECTIONS)

                # Debounce: เปลี่ยนท่าเมื่อเห็นท่าเดิมครบ STABLE_FRAMES เฟรมติดกัน
                history.append(raw)
                if len(history) == history.maxlen and len(set(history)) == 1:
                    stable = raw

                name, cmd = GESTURES.get(stable, NO_HAND)

                # ส่งคำสั่งซ้ำเป็นระยะ เพื่อให้ Failsafe ฝั่งบอร์ดไม่ตัดการทำงาน
                now = time.time()
                if now - last_send >= SEND_INTERVAL:
                    send(cmd)
                    last_send = now

                fingers_text = "-" if raw is None else str(raw)
                cv2.putText(frame, f"fingers now: {fingers_text}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
                cv2.putText(frame, f"{name}  [{cmd}]", (10, 65),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                cv2.imshow("Gesture Motor Control (q = quit)", frame)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        finally:
            # ออกจากโปรแกรมแล้วสั่งหยุดมอเตอร์เสมอ (UDP อาจตกหล่น จึงส่งซ้ำหลายครั้ง)
            for _ in range(5):
                send("S")
                time.sleep(0.02)
            if ser:
                ser.close()
            if sock:
                sock.close()
            cap.release()
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
