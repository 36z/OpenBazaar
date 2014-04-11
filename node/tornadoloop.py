import sys
import json

import tornado.ioloop
import tornado.web
from zmq.eventloop import ioloop, zmqstream
import zmq
ioloop.install()

from crypto2crypto import CryptoTransportLayer
from market import Market
from ws import WebSocketHandler, ProtocolHandler


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.redirect("/html/index.html")

class NickHandler(tornado.web.RequestHandler):
    def initialize(self, node):
        self.node = node

    def get(self, nick):
        self.write("todo: Show user content for {nick}".format(nick=nick))
        self.node.send_get_page(nick)


class MessageHandler(tornado.web.RequestHandler):
    def initialize(self, node):
        self.node = node

    def get(self):
        self.write("todo: Show all incoming messages")


class MarketApplication(tornado.web.Application):

    def __init__(self):
        settings = dict(debug=True)
        self.transport = CryptoTransportLayer(12345)
        self.transport.join_network()
        #self.protocol_handler = ProtocolHandler(self.transport)
        self.market = Market(self.transport)
        handlers = [
            (r"/", MainHandler),
            (r"/main", MainHandler),
            (r"/nick/(.*)", NickHandler, dict(node=self.market)),
            (r"/html/(.*)", tornado.web.StaticFileHandler, {'path': './html'}),
            (r"/mail", MessageHandler, dict(node=self.market)),
            (r"/ws", WebSocketHandler, dict(transport=self.transport, node=self.market))
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

