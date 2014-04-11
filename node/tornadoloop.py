import sys
import json

import tornado.ioloop
import tornado.web
from zmq.eventloop import ioloop, zmqstream
import zmq
ioloop.install()

from crypto2crypto import CryptoTransportLayer
from market import Market


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("Hello, world")

class NickHandler(tornado.web.RequestHandler):
    def initialize(self, transport):
        self.transport = transport

    def get(self, nick):
        self.write("todo: Show user content for {nick}".format(nick=nick))


class MessageHandler(tornado.web.RequestHandler):
    def initialize(self, transport):
        self.transport = transport

    def get(self):
        self.write("todo: Show all incoming messages")


class MarketApplication(tornado.web.Application):

    def __init__(self):
        settings = dict(debug=True)
        self.transport = CryptoTransportLayer(12345)
        self.transport.join_network()
        self.market = Market(self.transport)
        handlers = [
            (r"/foo", MainHandler),
            (r"/nick/(.*)", NickHandler, dict(transport=self.transport)),
            (r"/mail", MessageHandler, dict(transport=self.transport))
        ]
        tornado.web.Application.__init__(self, handlers, **settings)


if __name__ == "__main__":
    application = MarketApplication()
    error = True
    port = 8888
    while error and port < 8988:
        try:
            application.listen(port)
            error = False
        except:
            port += 1
    print " - started user port on %s" % port
    tornado.ioloop.IOLoop.instance().start()

