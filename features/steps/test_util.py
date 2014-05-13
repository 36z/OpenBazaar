import json
from tornado.ioloop import IOLoop
from tornado import gen
from tornado.websocket import websocket_connect


def ws_connect(port):
    @gen.coroutine
    def client():
        client = yield websocket_connect('ws://localhost:%s/ws' % port)
        message = yield client.read_message()
        raise gen.Return(json.loads(message))

    return IOLoop.current().run_sync(client)


def ws_send(string, port):
    @gen.coroutine
    def client():
        client = yield websocket_connect('ws://localhost:%s/ws' % port)
        message = yield client.read_message()
        client.write_message(json.dumps(string))
        message = yield client.read_message()
        raise gen.Return(json.loads(message))

    return IOLoop.current().run_sync(client)
