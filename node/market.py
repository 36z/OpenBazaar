from protocol import shout, page, query_page
from reputation import Reputation


class Market(object):
    def __init__(self, transport):
        transport.log("[market] Initializing")

        # for now we have the id in the transport
        self._myself = transport._myself
        self._peers = transport._peers
        self._transport = transport

        self.reputation = Reputation(self._transport)


        # if something comes in, store it:
        self.nicks = {}
        self.pages = {}

        # register callbacks for incoming events
        transport.add_callback('peer', self.on_peer)
        transport.add_callback('query_page', self.on_query_page)
        transport.add_callback('page', self.on_page)

        self.load_page()

        # send something
        transport.send(shout({'text': 'xxxxx'}))

    def load_page(self):
        f = open('shop/myshop.txt')
        data = f.read()
        f.close()
        self.mypage = data
        self.signature = self._transport._myself.sign(data)

    def query_page(self, pubkey):
        self._transport.send(protocol.query_page(pubkey))

    def on_page(self, page):
        self._transport.log("[market] got page " + str(page))
        pubkey = page.get('pubkey')
        page = page.get('text')
        if pubkey and page:
            self.pages[pubkey] = page
        

    def on_query_page(self, peer):
        self._transport.log("[market] query page " + str(peer))
        self._transport.send(page(self._transport._myself.get_pubkey(), self.mypage, self.signature))

    def on_peer(self, peer):
        self._transport.log("[market] new peer")

