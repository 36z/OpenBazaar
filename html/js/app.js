angular.module('app', [])

angular.module('app').directive('identicon', function () {
    return {
      restrict: 'E', // element
      scope: {
        hash: '=',
        iconSize: '='
      },
      link: function(scope, element, attrs) {
        var iconSize = scope.iconSize || 32;

        // Create the identicon
        function createFromHex(dataHex) {
          var data = new Identicon(dataHex, iconSize).toString();
          element.html('<img class="identicon" src="data:image/png;base64,' + data + '">');
        }
        // Watch for hash changes
        scope.$watch('hash', function() {
          if (scope.hash) {
            var tohash = scope.hash.substring(32, 64)
            createFromHex(tohash);
          }
        })
      }
    }
  });

angular.module('app').controller('Market', ['$scope', function($scope) {

  $scope.page = false
  $scope.shouts = [];
  $scope.newShout = ""
  $scope.searching = ""
  $scope.currentReviews = []
  $scope.myOrders = []
  $scope.myReviews = []
  $scope.createShout = function() {
     // launch a shout
     var newShout = {'type': 'shout', 'text': $scope.newShout}
     socket.send('shout', newShout)
     $scope.shouts.push(newShout)
     $scope.newShout = '';
  }

  $scope.peers = [];
  $scope.peerIds = [];
  $scope.reviews = {};
  $scope.awaitingShop = null;
  $scope.queryShop = function(peer) {
     $scope.awaitingShop = peer.pubkey;
     var query = {'type': 'query_page', 'pubkey': peer.pubkey}
     socket.send('query_page', query)
  }

 // Open the websocket connection and handle messages
  var socket = new Connection(function(msg) {   
   switch(msg.type) {
      case 'peer':
         $scope.parse_peer(msg)
         break;
      case 'page':
         $scope.parse_page(msg)
         break;
      case 'myself':
         $scope.parse_myself(msg)
         break;
      case 'shout':
         $scope.parse_shout(msg)
         break;
      case 'order':
         $scope.parse_order(msg)
         break;
      case 'reputation':
         $scope.parse_reputation(msg)
         break;
      case 'proto_response_pubkey':
         $scope.parse_response_pubkey(msg)
         break;
      default:
         console.log("Unhandled message!",msg)
         break;
    }
  })

  var add_review_to_page = function(pubkey, review) {
    var found = false;
    
    if (!$scope.reviews.hasOwnProperty(pubkey)) {
        $scope.reviews[pubkey] = []
    }
    $scope.reviews[pubkey].forEach(function(_review) {    	
        if (_review.sig == review.sig && _review.subject == review.subject && _review.pubkey == review.pubkey) {
           console.log("Found a review for this market")
           found = true
        }
    });
    if (!found) {
        // check if the review is about me
        if ($scope.myself.pubkey == review.subject) {
        	console.log("Found review for myself")
            $scope.myReviews.push(review)
        }
        $scope.reviews[pubkey].push(review)
    }
  }

  $scope.parse_order = function(msg) {
  	  
  	  console.log("Order update");
  	  
      if ($scope.myOrders.hasOwnProperty(msg.id)) {
          console.log("Updating order!")
          $scope.myOrders[msg.id].state = msg.state
          $scope.myOrders[msg.id].tx = msg.tx
          $scope.myOrders[msg.id].escrows = msg.escrows
          $scope.myOrders[msg.id].address = msg.address
          return;
      } else {
          console.log(msg);
          $scope.myOrders.push(msg);          
          console.log($scope.myOrders);
          return;
      }
      if (!$scope.$$phase) {
      	 console.log($scope.myOrders);
         //$scope.$apply();
      }
  }

  $scope.parse_response_pubkey = function(msg) {
      var pubkey = msg.pubkey;
      var nickname = msg.nickname;
      $scope.peers.forEach(function(peer) {
          if (peer.pubkey == pubkey) {
             // this peer!!
             peer.nickname = msg.nickname;
             if ($scope.searching == msg.nickname) {
                 $scope.queryShop(peer)
             }
          }
      });
      if (!$scope.$$phase) {
      	
         $scope.$apply();
      }
  }

  // Peer information has arrived
  $scope.parse_reputation = function(msg) {
    console.log('Parsing reputation', msg.reviews)
    msg.reviews.forEach(function(review) {
    
        add_review_to_page(review.subject, review);
    });
    if (!$scope.$$phase) {
       $scope.$apply();
    }
  }

  $scope.parse_page = function(msg) {
    
    if (msg.pubkey != $scope.awaitingShop)
       return
    if (!$scope.reviews.hasOwnProperty(msg.pubkey)) {
        $scope.reviews[msg.pubkey] = []
    }
    $scope.currentReviews = $scope.reviews[msg.pubkey]
    $scope.page = msg
    
    // Write in store content into the HTML
    var contentDiv = document.getElementById('page-content')
    contentDiv.innerHTML = msg.text;
    
    console.log("Parse orders:"+$scope.myOrders);
    
    if (!$scope.$$phase) {
       $scope.$apply();
    }
  }
  $scope.parse_peer = function(msg) {
    if ($scope.peerIds.indexOf(msg.uri) == -1) {
      $scope.peers.push(msg)
      $scope.peerIds.push(msg.uri)
    }
    if (!$scope.$$phase) {
       $scope.$apply();
    }
  }
  
  $scope.review= {rating:5, text:""}
  $scope.addReview = function() {
     
     var query = {'type': 'review', 'pubkey': $scope.page.pubkey, 'text': $scope.review.text, 'rating': parseInt($scope.review.rating)}
     socket.send('review', query)

     // store in appropriate format (its different than push format :P)
     add_review_to_page($scope.page.pubkey, {type: 'review', 'pubkey': $scope.myself.pubkey, 'subject': $scope.page.pubkey, 'rating': query.rating, text: query.text})

     $scope.review.rating = 5;
     $scope.review.text = '';
     $scope.showReviewForm = false;
  }
  
  // My information has arrived
  $scope.parse_myself = function(msg) {
    $scope.myself = msg;
    if (!$scope.$$phase) {
       $scope.$apply();
    }
    
    console.log('Reputation for myself', msg);
    console.log('Reviews: ', $scope.reviews);
    
    msg.reputation.forEach(function(review) {       
       add_review_to_page($scope.myself.pubkey, review)
    });
    msg.peers.forEach(function(peer) {
       $scope.parse_peer(peer)
    });
  }
  
  // A shout has arrived
  $scope.parse_shout = function(msg) {
    $scope.shouts.push(msg)
    if (!$scope.$$phase) {
       $scope.$apply();
    }
  }
  $scope.search = ""
  $scope.searchNickname = function() {
     var query = {'type': 'search', 'text': $scope.search };
     $scope.searching = $scope.search;
     socket.send('search', query)
     $scope.search = ""
  }

  // Create a new order and send to the network
  $scope.newOrder = {text:'', tx: ''}
  $scope.createOrder = function() {
      $scope.creatingOrder = false;
      var newOrder = {
          'text': $scope.newOrder.text,
          'state': 'new',
          'buyer': $scope.myself.pubkey,
          'seller': $scope.page.pubkey
      }
      $scope.newOrder.text = '';		
      //$scope.orders.push(newOrder);     // This doesn't really do much since it gets wiped away
      socket.send('order', newOrder);
  }
  $scope.payOrder = function(order) {
      order.state = 'payed'
      order.tx = $scope.newOrder.tx;
      $scope.newOrder.tx = '';
      socket.send('order', order);
  }
  $scope.receiveOrder = function(order) {
      order.state = 'received'
      socket.send('order', order);
  }
  $scope.sendOrder = function(order) {
      order.state = 'sent'
      socket.send('order', order);
  }

}])
