from protocol import shout, proto_page, query_page
from reputation import Reputation
from orders import Orders
import protocol
import sys
import json
import lookup
from pymongo import MongoClient

class Market(object):

    def __init__(self, transport):
        
        transport.log("[Market] Initializing")

        # for now we have the id in the transport
        self._myself = transport._myself
        self._peers = transport._peers
        self._transport = transport
        self.query_ident = None

        self.reputation = Reputation(self._transport)
        self.orders = Orders(self._transport)
        self.order_entries = self.orders._orders
        
        # TODO: Persistent storage of nicknames and pages
        self.nicks = {}
        self.pages = {}
        
        # Connect to database
        MONGODB_URI = 'mongodb://localhost:27017'         
        _dbclient = MongoClient()
        self._db = _dbclient.openbazaar

        # Register callbacks for incoming events
        transport.add_callback('query_myorders', self.on_query_myorders)
        transport.add_callback('peer', self.on_peer)
        transport.add_callback('query_page', self.on_query_page)
        transport.add_callback('page', self.on_page)
        transport.add_callback('negotiate_pubkey', self.on_negotiate_pubkey)
        transport.add_callback('proto_response_pubkey', self.on_response_pubkey)

        self.load_page()

        # Send Market Shout
        transport.send(shout({'text': 'Market Initialized'}))
        

    def lookup(self, msg):
           
        if self.query_ident is None:
            self._transport.log("Initializing identity query")
            self.query_ident = lookup.QueryIdent()
                        
        nickname = str(msg["text"])
        key = self.query_ident.lookup(nickname)
        if key is None:
            print "Key not found for this nickname"
            return ("Key not found for this nickname", None)
        print "Found key:", key.encode("hex")
        if self._transport.nick_mapping.has_key(nickname):
            print "Already have a cached mapping, just adding key there."
            response = {'nickname': nickname, 'pubkey': self._transport.nick_mapping[nickname][1].encode('hex'), 'signature': self._transport.nick_mapping[nickname][0].encode('hex'), 'type': 'response_pubkey', 'signature': 'unknown'}
            self._transport.nick_mapping[nickname][0] = key
            return (None, response)

        self._transport.nick_mapping[nickname] = [key, None]
        self._transport.send(protocol.negotiate_pubkey(nickname, key))


	# Load default information for your market from your file
    def load_page(self):
    
    	self._transport.log("[Market] Loading market config from " + sys.argv[1])
    
        with open(sys.argv[1]) as f:
            data = json.loads(f.read())
                    
            
        self._transport.log("[Market] Configuration data: " + json.dumps(data))    
            
        assert "desc" in data
        nickname = data["nickname"]
        desc = data["desc"]
        
        tagline = "%s: %s" % (nickname, desc)
        self.mypage = tagline
        self.nickname = nickname
        self.signature = self._transport._myself.sign(tagline)
        
        self._transport.log("[Market] Tagline signature: " + self.signature.encode("hex"))
        
    def save_settings(self):
    
        self._transport.log('Save settings')
        
        self._db.settings.update
        
        
        

    def query_page(self, pubkey):
        self._transport.send(query_page(pubkey))

    def on_page(self, page):
        self._transport.log("[Market] Page returned: " + str(page))
        
        pubkey = page.get('pubkey')
        page = page.get('text')
        
        #print "Orders: ", self.orders.print_orders()
        
        if pubkey and page:
            self.pages[pubkey] = page
        
	# Return your page info if someone requests it on the network
    def on_query_page(self, peer):
        self._transport.log("[Market] Someone is querying for your page")        
        self._transport.send(proto_page(self._transport._myself.get_pubkey(), self.mypage, self.signature, self.nickname))
        
    def on_query_myorders(self, peer):
        self._transport.log("[Market] Someone is querying for your page")        
        self._transport.send(proto_page(self._transport._myself.get_pubkey(), self.mypage, self.signature, self.nickname))

    def on_peer(self, peer):
        self._transport.log("[Market] New peer")

    def on_negotiate_pubkey(self, ident_pubkey):
        self._transport.log("[Market] Someone is asking for your real pubKey")
        assert "nickname" in ident_pubkey
        assert "ident_pubkey" in ident_pubkey
        nickname = ident_pubkey['nickname']
        ident_pubkey = ident_pubkey['ident_pubkey'].decode("hex")
        self._transport.respond_pubkey_if_mine(nickname, ident_pubkey)

    def on_response_pubkey(self, response):
        self._transport.log("[Market] got a pubkey!")
        assert "pubkey" in response
        assert "nickname" in response
        assert "signature" in response
        pubkey = response["pubkey"].decode("hex")
        signature = response["signature"].decode("hex")
        nickname = response["nickname"]
        # Cache mapping for later.
        if not self._transport.nick_mapping.has_key(nickname):
            self._transport.nick_mapping[nickname] = [None, pubkey]
        # Verify signature here...
        # Add to our dict.
        self._transport.nick_mapping[nickname][1] = pubkey
        self._transport.log("[market] mappings: ###############")
        for k, v in self._transport.nick_mapping.iteritems():
            self._transport.log("'%s' -> '%s' (%s)" % (
                k, v[1].encode("hex") if v[1] is not None else v[1],
                v[0].encode("hex") if v[0] is not None else v[0]))
        self._transport.log("##################################")

