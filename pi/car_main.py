import car_control as cc
import picamera
import urlparse
import socket
import httplib
import urllib
import time
import sys
import os
import io

from config_parser import loadConfig, printDict
from autobahn.twisted.websocket import WebSocketClientProtocol, WebSocketClientFactory
from twisted.internet import reactor
from twisted.internet import task
from multiprocessing import Process

def applyCommands(up, down, left, right):
    #driving
    if up == "on": control.drive(control.DRIVE_FORWARD)
    elif down == "on": control.drive(control.DRIVE_BACKWARD)
    else: control.drive(control.DRIVE_STOP)
    #steering
    if left == "on": control.steer(control.STEER_LEFT)
    elif right == "on": control.steer(control.STEER_RIGHT)
    else: control.steer(control.STEER_STOP)
    print "Got state UP:", up, "DOWN:", down, "LEFT:", left, "RIGHT:", right

class WebSocketClient(WebSocketClientProtocol):
    def __init__(self):
        self.pingTask = task.LoopingCall(self.ping)
        self.gotPong = True
    
    def onOpen(self):
        print "Websocket connection opened"
        print "Car is ready for driving"
        factory.setConnected(True)
        self.sendMessage(urllib.urlencode({"token": config["secret key"], "name": config["name"]}))
        self.pingTask.start(float(config["ping interval"]))
    
    def onMessage(self, payload, isBinary):
        try:
            request = urlparse.parse_qs(payload)
            applyCommands(request["up"][0].lower(), request["down"][0].lower(), request["left"][0].lower(), request["right"][0].lower())
        except KeyError:
            control.stopMotors()
            print "invalid commands"
        
    def onClose(self, wasClean, code, reason):
        try:
            print "Connection closed with code:", code, "and reason:", reason
            control.stopMotors()
            self.pingTask.stop()
        except Exception as e:
            print e
    
    def ping(self):
        if self.gotPong:
            self.sendPing()
            self.gotPong = False
        else:
            print "Did not get PONG... closing connection"
            control.stopMotors()
            self.sendClose()
    
    def onPong(self, payload):
        self.gotPong = True

class WebSocketFactory(WebSocketClientFactory):
    connected = True    
        
    def clientConnectionFailed(self, connector, reason):
        self.disconnected(connector, reason)
    
    def clientConnectionLost(self, connector, reason):
        self.disconnected(connector, reason)
    
    def setConnected(self, c):
        self.connected = c
        control.LED("green", c)
        control.LED("red", not c)
    
    def disconnected(self, connector, reason):
        if self.connected:
            print "Connection unsuccessful:", reason
            print "reconnecting..."
            self.setConnected(False)
        connector.connect()

def streaming():
    import camera_specs as cs
    cameraSpecs = cs.CameraSpecs(desiredFPS = 25)
    camera = picamera.PiCamera()
    #camera.color_effects = (128, 128) #grayscale image
    stream = io.BytesIO()
    print "Connecting stream..."
    try:
        conn = httplib.HTTPConnection(config["server ip"], int(config["stream port"]), timeout=3)
        #conn.set_debuglevel(1)
        conn.putrequest("GET", "/streamreg?" + urllib.urlencode({"token": config["secret key"], "name": config["name"]}))
        conn.putheader("Content-Length", "4000000000000")
        conn.endheaders()
        conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1) #hack may increase transmission rate
        conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_CORK, 0) #hack may increase transmission rate
        print "Streaming started"
        while True:
            print "Camera resolution:", cameraSpecs.resolution
            print "Camera framerate:", cameraSpecs.framerate
            camera.resolution = cameraSpecs.resolution
            camera.framerate = cameraSpecs.framerate
            for image in camera.capture_continuous(stream, format='jpeg', use_video_port=True, quality = 10):
                conn.send("--jpgboundary\n")
                conn.send("Content-type: image/jpeg\n")
                conn.send("Content-length: " + str(stream.tell()) + "\n\n")
                conn.send(stream.getvalue())
                cameraSpecs.frameSent()
                print "%.2f" % cameraSpecs.FPS, "FPS,", "%.2f" % (stream.tell() / 1024.0), "KB"
                stream.seek(0)
                stream.truncate()
                if cameraSpecs.checkChange():
                    break
            
    except Exception as e:
        print "Error streaming: ", e
        camera.close()
        conn.close()
        streaming()

#****MAIN****#
print "Process nicesness", os.nice(-20)

#initialize car control
control = cc.Control()
control.LED("red", True)

#read default config file (car.config) or the one provided as program argument
config = loadConfig(sys.argv[2]) if len(sys.argv) > 2 else loadConfig()
printDict("Config:", config)

#connect websocket
"""from twisted.python import log
log.startLogging(sys.stdout)"""

factory = WebSocketFactory(debug = False)
factory.protocol = WebSocketClient
reactor.connectTCP(config["server ip"], int(config["ws port"]), factory)

runStreaming = True
if len(sys.argv) > 1:
    runStreaming = sys.argv[1].lower() == "true"
if runStreaming:
    streamProcess = Process(target = streaming)
    streamProcess.daemon = True
    streamProcess.start()
    
reactor.run()
