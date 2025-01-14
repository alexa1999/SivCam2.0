import time
import numpy as np
import os
import cv2
from threading import Thread
import threading
from argparse import ArgumentParser
from MotionDetection import MotionDetector
from flask import Response
from flask import Flask
from flask import render_template
from ObjectDetectorTFLITE import ObjectDetectorTFLITE, read_class_colors, scale_boxes, read_class_names, draw_bbox


class ImageWeb():

    def __init__(self):
        self.frame = None

    def generate_frames(self):
        while True:
            with lock:
                if self.frame is None:
                    continue
                (flag, encodedImage) = cv2.imencode(".jpg", self.frame)
                if not flag:
                    continue
                bytes_to_send = (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' +
                                 bytearray(encodedImage) + b'\r\n')

            yield bytes_to_send


class StartVideoPro(Thread):
    def __init__(self, container, min_area=1000, delay=1.0, camera_resolution=(640, 480), camera_type="USB",
                 AI=False):
        Thread.__init__(self)
        # configuracion init
        self.camera_resolution = camera_resolution
        self.stopped = False
        self.md = MotionDetector()
        self.output_name = ""
        self.save_time = 0
        self.container = container
        self.vid = None
        self.camera_type = camera_type
        self.min_area = min_area
        self.delay = delay
        self.AI = AI
        self.classes = read_class_names("./data/coco.names")
        class_color_filename = './data/colors.yaml'
        self.colors, _ = read_class_colors(class_color_filename)
        cfg = {"CLASSES": "./data/coco.names",
               "SCORE_THRESHOLD": 0.3,
               "IOU_THRESHOLD": 0.1,
               "MODEL_PB_FILE": "./data/ssd-mobilenet-v2_uint8.tflite"
               }
        self.SSD_lite = ObjectDetectorTFLITE(cfg)

    def save_frame(self, frame):
        date_time = time.strftime("%m_%d_%Y-%H:%M:%S")
        self.output_name = os.path.join("./static/images", date_time + ".jpg")
        self.save_time = time.time()
        cv2.putText(frame, os.path.basename(self.output_name),
                    (0, 10), cv2.FONT_HERSHEY_DUPLEX, 0.5, (255, 255, 255))
        cv2.imwrite(self.output_name, frame)
        cv2.putText(frame, "Saving frame", (0, 10),
                    cv2.FONT_HERSHEY_DUPLEX, 0.5, (0, 0, 255), 1)

    def run_ssd_lite_model(self, frame):
        image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        boxes, scores, classes_out = self.SSD_lite.predict_image(image)
        h, w = image.shape[:2]
        boxes_scaled = scale_boxes(boxes[0], w, h)
        new_boxes = [[b[0], b[1], b[2], b[3], s, cl] for b, s, cl in zip(boxes_scaled, scores[0], classes_out[0]) if
                     s > 0.3]
        return new_boxes

    def run_motion_detection(self, frame):
        # Deteccion de movimiento
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray_blur = cv2.GaussianBlur(gray, (7, 7), 0)
        #cv2.imshow("blur",gray_blur)
        self.md.update(gray_blur)
        thresh = np.zeros(frame.shape)
        thresh, md_boxes = self.md.detect(gray_blur)
        if md_boxes is not None:
            total_area = 0
            for b in md_boxes:
                #algo se mueve
                cv2.rectangle(frame, (b[0], b[1]), (b[2], b[3]),(0, 0, 255), 1)
                total_area += (b[2] - b[0]) * (b[3] - b[1])
            if total_area > self.min_area:
                if self.AI:
                    boxes = self.run_ssd_lite_model(frame)
                    frame = draw_bbox(frame, boxes, show_label=True,
                                                colors=self.colors, classes=self.classes)

                    num_relevant_objects = len([c[5] for c in boxes if c[5] == 0 or c[5] == 15 or c[5] == 16])

                    if time.time() - self.save_time > self.delay and num_relevant_objects > 0:
                        self.save_frame(frame)
                else:
                    if time.time() - self.save_time > self.delay:
                        self.save_frame(frame)


    def run_camera(self):
        self.vid = cv2.VideoCapture(2)
        try:
            while True:
                ret, frame = self.vid.read()
                if not ret:
                    continue
                # Detección de movimiento
                self.run_motion_detection(frame)
                with lock:
                    self.container.frame = frame

        finally:
            self.stopped = True

    def run(self):
        if self.camera_type == "USB":
            self.run_camera()
        else:
            pass
            #self.run_pi_camera()


app = Flask(__name__)
lock = threading.Lock()
container = ImageWeb()


@ app.route("/")
def index():
    return render_template("index.html")


@ app.route("/summary")
def summary():
    imgs = ["images/" + file for file in os.listdir('static/images')]
    imgs.sort(reverse=True)
    days = [x[7:17] for x in imgs]
    days = list(set(days))
    days.sort(reverse=True)
    return render_template("summary.html", days=days, imgs=imgs)


@ app.route("/video_summary")
def video_summary():
    vids = ["video_summary/" + \
        file for file in os.listdir('static/video_summary')]
    vids.sort(reverse=True)
    return render_template("video_summary.html", vids=vids)


@ app.route("/video_feed")
def video_feed():
    return Response(container.generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

@ app.route('/make_summary')
def do_progress():
    return render_template('progress.html')

@ app.route('/progress')
def progress():
    day = time.strftime("%m_%d_%Y")
    imgs = ["static/images/" + \
        file for file in os.listdir('static/images') if day in file]
    imgs.sort()
    return Response(make_video(imgs, f"static/video_summary/{day}.mp4"), mimetype='text/event-stream')


if __name__ == "__main__":

    parser = ArgumentParser()
    parser.add_argument('--port', type=int,dest='port',default=8887,help='socket port',required=False)
    parser.add_argument('--host', type=str,dest='host',default='0.0.0.0',help='ip',required=False)
    parser.add_argument('-p', type=str,dest='camera_type',default='USB',help='use piCamera',required=False)
    parser.add_argument('--area', type=int,dest='area',default=1000,help='area ',required=False)
    parser.add_argument('--delay', type=float,dest='delay',default=1.0,help='minimum delay',required=False)
    parser.add_argument('--AI',action='store_true',default=False,help='model',required=False)
    args = vars(parser.parse_args())

    host = args['host']
    port = args['port']

    threads = []

    newthread = StartVideoPro(container, min_area=args['area'], delay=args['delay'], camera_type=args['camera_type'])
    newthread.start()
    threads.append(newthread)

    #flask object
    app.run(host=args["host"], port=args["port"], debug=True,
            threaded=True, use_reloader=False)

    for t in threads:
        t.join()
