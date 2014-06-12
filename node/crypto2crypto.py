import constants
from contact import Contact
import hashlib
import json
import logging
from market import Market
import obelisk
from obelisk import bitcoin
import os
from protocol import hello_request, hello_response, proto_response_pubkey
from pymongo import MongoClient
import pyelliptic as ec
from p2p import PeerConnection, TransportLayer
from threading import Thread
import time
import tornado
import traceback
from urlparse import urlparse
from dht import DHT



class CryptoPeerConnection(PeerConnection):

    def __init__(self, transport, address, pub=None, guid=None):

        self._priv = transport._myself
        self._pub = pub
        self._guid = guid
        self._transport = transport
        self._ip = urlparse(address).hostname
        self._port = urlparse(address).port

        self._log = logging.getLogger('[%s] %s' % (transport._market_id, self.__class__.__name__))

        PeerConnection.__init__(self, transport, address)

        if pub == None or guid == None:
          self._log.debug('About to say hello')
          msg = self.send_raw(json.dumps({'type':'hello', 'pubkey':transport.pubkey, 'uri':transport._uri, 'senderGUID':transport.guid }))

          if msg:
            msg = json.loads(msg)
            self._guid = msg['senderGUID']
            self._pub = msg['pubkey']


        self._log.info(transport._dht._activePeers)


    def encrypt(self, data):
        return self._priv.encrypt(data, self._pub.decode('hex'))

    def send(self, data):

        # Include guid
        data['guid'] = self._guid
        data['senderGUID'] = self._transport.guid
        data['uri'] = self._transport._uri
        data['pubkey'] = self._transport.pubkey

        self._log.debug('Sending to peer: %s %s' % (self._guid, data))
        print self.send_raw(self.encrypt(json.dumps(data)))

    def on_message(self, msg, callback=None):
        # this are just acks
        pass

    def peer_to_tuple(self):
        return (self._ip, self._port, self._guid)


class CryptoTransportLayer(TransportLayer):

    def __init__(self, my_ip, my_port, market_id):

        self._log = logging.getLogger('[%s] %s' % (market_id, self.__class__.__name__))

        # Connect to database
        MONGODB_URI = 'mongodb://localhost:27017'
        _dbclient = MongoClient()
        self._db = _dbclient.openbazaar

        self._market_id = market_id
        self.nick_mapping = {}
        self._uri = "tcp://%s:%s" % (my_ip, my_port)

        # Set up
        self._setup_settings()

        self._dht = DHT(self, market_id, self.settings)

        self._myself = ec.ECC(pubkey=self.pubkey.decode('hex'), privkey=self.secret.decode('hex'), curve='secp256k1')

        TransportLayer.__init__(self, market_id, my_ip, my_port, self.guid)

        # Set up callbacks
        self.add_callback('ping', self._dht._on_ping)
        self.add_callback('findNode', self._findNode)
        self.add_callback('findNodeResponse', self._findNodeResponse)
        self.add_callback('store', self._storeValue)


    def _storeValue(self, msg):
        guid = msg['senderGUID']
        uri = msg['uri']
        pubkey = msg['pubkey']

        msg['new_peer'] = CryptoPeerConnection(self, uri, pubkey, guid)
        self._dht._on_storeValue(msg)

    def _findNode(self, msg):

        guid = msg['senderGUID']
        uri = msg['uri']
        pubkey = msg['pubkey']

        msg['new_peer'] = CryptoPeerConnection(self, uri, pubkey, guid)
        self._dht._on_findNode(msg)

    def _findNodeResponse(self, msg):

        guid = msg['senderGUID']
        uri = msg['uri']
        pubkey = msg['pubkey']

        #msg['new_peer'] = CryptoPeerConnection(self, uri, pubkey, guid)
        self._dht._on_findNodeResponse(self, msg)

    def _setup_settings(self):

        self.settings = self._db.settings.find_one({'id':"%s" % self._market_id})

        if self.settings:
            self.nickname = self.settings['nickname'] if self.settings.has_key("nickname") else ""
            self.secret = self.settings['secret']
            self.pubkey = self.settings['pubkey']
            self.guid = self.settings['guid']
        else:
            self.nickname = 'Default'
            self._generate_new_keypair()
            self.settings = self._db.settings.find_one({'id':"%s" % self._market_id})

        self._log.debug('Retrieved Settings: %s', self.settings)


    def _generate_new_keypair(self):

      # Generate new keypair
      key = ec.ECC(curve='secp256k1')
      self.secret = key.get_privkey().encode('hex')
      pubkey = key.get_pubkey()
      signedPubkey = key.sign(pubkey)
      self.pubkey = pubkey.encode('hex')
      self._myself = key

      # Generate a node ID by ripemd160 hashing the signed pubkey
      guid = hashlib.new('ripemd160')
      guid.update(signedPubkey)
      self.guid = guid.digest().encode('hex')

      self._db.settings.update({"id":'%s' % self._market_id}, {"$set": {"secret":self.secret, "pubkey":self.pubkey, "guid":self.guid}}, True)


    def join_network(self, seed_uri):

        self.listen(self.pubkey) # Turn on zmq socket

        if seed_uri:
            self._log.info('Initializing Seed Peer(s): [%s]' % (seed_uri))
            seed_peer = CryptoPeerConnection(self, seed_uri)
            self._dht.start(seed_peer)


    def getCryptoPeer(self, guid, uri, pubkey):

      if guid == self.guid:
        self._log.info('Trying to get cryptopeer for yourself')
        return

      peer = CryptoPeerConnection(self, uri, pubkey, guid=guid)
      return peer

    def addCryptoPeer(self, peer):

      peerExists = False
      for idx, aPeer in enumerate(self._activePeers):

        if aPeer._guid == peer._guid or aPeer._pub == peer._pub or aPeer._address == peer._address:

          self._log.info('guids or pubkey match')
          peerExists = True
          if peer._pub and aPeer._pub == '':
            self._log.info('no pubkey')
            aPeer._pub = peer._pub
            self._activePeers[idx] = aPeer

      if not peerExists and peer._guid != self._guid:
        self._log.info('Adding crypto peer %s' % peer._pub)
        self._routingTable.addContact(peer)
        self._dht.add_active_peer(peer)



    # Return data array with details from the crypto file
    # TODO: This needs to be protected better; potentially encrypted file or DB
    def load_crypto_details(self, store_file):
        with open(store_file) as f:
            data = json.loads(f.read())
        assert "nickname" in data
        assert "secret" in data
        assert "pubkey" in data
        assert len(data["secret"]) == 2 * 32
        assert len(data["pubkey"]) == 2 * 33

        return data["nickname"], data["secret"].decode("hex"), \
            data["pubkey"].decode("hex")

    def get_profile(self):
        peers = {}

        self.settings = self._db.settings.find_one({'id':"%s" % self._market_id})

        for uri, peer in self._peers.iteritems():
            if peer._pub:
                peers[uri] = peer._pub.encode('hex')
        return {'uri': self._uri, 'pub': self._myself.get_pubkey().encode('hex'),'nickname': self.nickname,
                'peers': peers}

    def respond_pubkey_if_mine(self, nickname, ident_pubkey):

        if ident_pubkey != self.pubkey:
            self._log.info("Public key does not match your identity")
            return

        # Return signed pubkey
        pubkey = self._myself.pubkey
        ec_key = obelisk.EllipticCurveKey()
        ec_key.set_secret(self.secret)
        digest = obelisk.Hash(pubkey)
        signature = ec_key.sign(digest)

        # Send array of nickname, pubkey, signature to transport layer
        self.send(proto_response_pubkey(nickname, pubkey, signature))

    def pubkey_exists(self, pub):

        for uri, peer in self._peers.iteritems():
            self._log.info('PEER: %s Pub: %s' %
                           (peer._pub.encode('hex'), pub.encode('hex')))
            if peer._pub.encode('hex') == pub.encode('hex'):
                return True

        return False

    def create_peer(self, uri, pub, node_guid):

        if pub:
            pub = pub.decode('hex')

        # Create the peer if public key is not already in the peer list
        # if not self.pubkey_exists(pub):
        self._peers[uri] = CryptoPeerConnection(self, uri, pub, node_guid)

        # Call 'peer' callbacks on listeners
        self.trigger_callbacks('peer', self._peers[uri])

        # else:
        #    print 'Pub Key is already in peer list'

    def send_enc(self, uri, msg):
        peer = self._peers[uri]
        pub = peer._pub

        # Now send a hello message to the peer
        if pub:
            self._log.info("Sending encrypted [%s] message to %s"
                           % (msg['type'], uri))
            peer.send(msg)
        else:
            # Will send clear profile on initial if no pub
            self._log.info("Sending unencrypted [%s] message to %s"
                           % (msg['type'], uri))
            self._peers[uri].send_raw(json.dumps(msg))


    def init_peer(self, msg):

        uri = msg['uri']
        pub = msg.get('pub')
        nickname = msg.get('nickname')
        msg_type = msg.get('type')
        guid = msg['guid']

        if not self.valid_peer_uri(uri):
            self._log.error("Invalid Peer: %s " % uri)
            return

        if uri not in self._peers:
            # Unknown peer
            self._log.info('Add New Peer: %s' % uri)
            self.create_peer(uri, pub, guid)

            if not msg_type:
                self.send_enc(uri, hello_request(self.get_profile()))
            elif msg_type == 'hello_request':
                self.send_enc(uri, hello_response(self.get_profile()))

        else:
            # Known peer
            if pub:
                # test if we have to update the pubkey
                if not self._peers[uri]._pub:
                    self._log.info("Setting public key for seed node")
                    self._peers[uri]._pub = pub.decode('hex')
                    self.trigger_callbacks('peer', self._peers[uri])

                if (self._peers[uri]._pub != pub.decode('hex')):
                    self._log.info("Updating public key for node")
                    self._peers[uri]._nickname = nickname
                    self._peers[uri]._pub = pub.decode('hex')

                    self.trigger_callbacks('peer', self._peers[uri])

            if msg_type == 'hello_request':
                # reply only if necessary
                self.send_enc(uri, hello_response(self.get_profile()))



    def on_message(self, msg):

        # here goes the application callbacks
        # we get a "clean" msg which is a dict holding whatever
        self._log.info("[On Message] Data received: %s" % msg)

        pubkey = msg.get('pubkey')
        uri = msg.get('uri')
        ip = urlparse(uri).hostname
        port = urlparse(uri).port
        guid = msg.get('senderGUID')

        self._dht.add_active_peer(self, (pubkey, uri, guid))
        self._dht.add_known_node((ip, port, guid))


        self.trigger_callbacks(msg['type'], msg)


    def on_raw_message(self, serialized):


        try:
            # Try to deserialize cleartext message
            msg = json.loads(serialized)
            self._log.info("Message Received [%s]" % msg.get('type', 'unknown'))

        except ValueError:
            try:
                # Encrypted?
                try:
                  msg = self._myself.decrypt(serialized)
                  msg = json.loads(msg)

                  self._log.info("Decrypted Message [%s]"
                               % msg.get('type', 'unknown'))
                except:
                  self._log.error("Could not decrypt message: %s" % msg)
                  return
            except:
                self._log.info("Bad Message: %s..."
                               % self._myself.decrypt(serialized))
                traceback.print_exc()
                return

        if msg.get('type') != '':

          msg_type = msg.get('type')
          msg_uri = msg.get('uri')
          msg_guid = msg.get('guid')



          #
          # if msg_type.startswith('hello') and msg_uri:
          #     self.init_peer(msg)
          #     for uri, pub in msg.get('peers', {}).iteritems():
          #         # Do not add yourself as a peer
          #         if uri != self._uri:
          #             self.init_peer({'uri': uri, 'pub': pub})
          #     self._log.info("Update peer table [%s peers]" % len(self._peers))
          #
          # elif msg_type == 'goodbye' and msg_uri:
          #     self._log.info("Received goodbye from %s" % msg_uri)
          #     self.remove_peer(msg_uri)
          #
          # else:
          self.on_message(msg)
