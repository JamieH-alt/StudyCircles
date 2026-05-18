import socket, threading, json, hashlib, os

class ChatServer:
    def __init__(self, host='127.0.0.1', port=5555):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind((host, port))
        self.server.listen()
        self.clients = {}  
        self.user_db = self.load_db("users.json") 
        self.groups = self.load_db("groups.json")
        self.invites = self.load_db("invites.json")
        print(f"[LOG] Server started on {host}:{port}")

    def load_db(self, filename):
        if os.path.exists(filename):
            with open(filename, "r") as f: return json.load(f)
        return {}

    def save_db(self, data, filename):
        with open(filename, "w") as f: json.dump(data, f)

    def handle_client(self, conn, addr):
        current_user = None 
        while True:
            try:
                data = conn.recv(8192).decode()
                if not data: break
                p = json.loads(data)
                cmd = p.get("type")
                sender = p.get("sender")
                target = p.get("target")

                if cmd == "REGISTER":
                    if sender not in self.user_db:
                        self.user_db[sender] = {"hash": p["content"], "pub_key": p.get("pub_key"), "friends": []}
                        self.save_db(self.user_db, "users.json")
                        current_user = sender
                        self.clients[sender] = conn
                        print(f"[LOG] NEW USER REGISTERED: {sender}")
                        conn.send(json.dumps({"type": "AUTH_SUCCESS"}).encode())
                    else: 
                        print(f"[LOG] Registration failed: {sender} already exists")
                        conn.send(json.dumps({"type": "AUTH_FAIL", "content": "Exists"}).encode())

                elif cmd == "LOGIN":
                    if sender in self.user_db and self.user_db[sender]["hash"] == p["content"]:
                        current_user = sender
                        self.clients[sender] = conn
                        self.user_db[sender]["pub_key"] = p.get("pub_key")
                        print(f"[LOG] USER LOGIN: {current_user}")
                        conn.send(json.dumps({"type": "AUTH_SUCCESS"}).encode())
                    else: 
                        print(f"[LOG] Login failed for user: {sender}")
                        conn.send(json.dumps({"type": "AUTH_FAIL", "content": "Denied"}).encode())

                elif cmd == "GET_FRIENDS":
                    friends = self.user_db.get(sender, {}).get("friends", [])
                    print(f"[LOG] {sender} requested their friends list ({len(friends)} friends)")
                    conn.send(json.dumps({"type": "FRIENDS_LIST", "content": friends}).encode())

                elif cmd == "ADD_TO_GROUP":
                    g_name, invitee = target, p.get("content")
                    
                    # 1. Get the sender's friend list
                    sender_friends = self.user_db.get(sender, {}).get("friends", [])

                    # 2. Check: Is the invitee a friend? Is the sender in the group?
                    if invitee in sender_friends:
                        if g_name in self.groups and sender in self.groups[g_name]:
                            if invitee not in self.invites: self.invites[invitee] = []
                            
                            self.invites[invitee].append({"type": "GROUP_INVITE", "from": sender, "group": g_name})
                            self.save_db(self.invites, "invites.json")
                            
                            print(f"[LOG] {sender} invited friend {invitee} to {g_name}")
                            if invitee in self.clients:
                                self.clients[invitee].send(json.dumps({"type": "INFO", "content": f"New Group Invite: {g_name}"}).encode())
                        else:
                            print(f"[LOG] {sender} tried to invite to {g_name} but isn't a member/owner")
                    else:
                        print(f"[LOG] {sender} blocked from inviting {invitee}: Not in friend list.")
                        conn.send(json.dumps({"type": "INFO", "content": f"Error: You can only invite friends to groups."}).encode())

                elif cmd == "ADD_FRIEND":
                    # target is the person receiving the request
                    if target in self.user_db:
                        if target not in self.invites: 
                            self.invites[target] = []
                        
                        # Check if a request from this sender already exists to avoid spam
                        existing = [i for i in self.invites[target] if i.get('type') == 'FRIEND_REQUEST' and i.get('from') == sender]
                        
                        if not existing:
                            self.invites[target].append({"type": "FRIEND_REQUEST", "from": sender})
                            self.save_db(self.invites, "invites.json")
                            print(f"[LOG] Friend Request: {sender} -> {target}")
                            
                            # Real-time alert if they are online
                            if target in self.clients:
                                self.clients[target].send(json.dumps({
                                    "type": "INFO", 
                                    "content": f"New Friend Request from: {sender}"
                                }).encode())
                        else:
                            print(f"[LOG] {sender} already has a pending request to {target}")
                    else:
                        print(f"[LOG] {sender} tried to add non-existent user: {target}")

                elif cmd == "ACCEPT_INVITE":
                    inv_type = p.get("inv_type") # "FRIEND" or "GROUP"
                    val = p.get("target")       # username or groupname
                    
                    if inv_type == "FRIEND":
                        if val in self.user_db:
                            if val not in self.user_db[sender]["friends"]: self.user_db[sender]["friends"].append(val)
                            if sender not in self.user_db[val]["friends"]: self.user_db[val]["friends"].append(sender)
                            self.save_db(self.user_db, "users.json")
                            # Safely remove the invite
                            self.invites[sender] = [i for i in self.invites.get(sender, []) if not (i.get('type') == 'FRIEND_REQUEST' and i.get('from') == val)]
                            print(f"[LOG] {sender} accepted friend request from {val}")

                    elif inv_type == "GROUP":
                        if val in self.groups:
                            if sender not in self.groups[val]: self.groups[val].append(sender)
                            self.save_db(self.groups, "groups.json")
                            self.invites[sender] = [i for i in self.invites.get(sender, []) if not (i.get('type') == 'GROUP_INVITE' and i.get('group') == val)]
                            print(f"[LOG] {sender} joined group {val}")
                    
                    self.save_db(self.invites, "invites.json")
                    conn.send(json.dumps({"type": "INFO", "content": f"Accepted {inv_type}: {val}"}).encode())

                elif cmd == "GET_GROUPS":
                    user_groups = [g for g, members in self.groups.items() if sender in members]
                    conn.send(json.dumps({"type": "GROUPS_LIST", "content": user_groups}).encode())

                elif cmd == "LIST_INVITES":
                    my_invites = self.invites.get(sender, [])
                    conn.send(json.dumps({"type": "INVITES_LIST", "content": my_invites}).encode())

                elif cmd == "DIRECT_MSG":
                    print(f"[LOG] DM: {sender} -> {target}")
                    if target in self.clients:
                        self.clients[target].send(json.dumps(p).encode())
                    else:
                        print(f"[LOG] DM failed: {target} is offline")

                elif cmd == "CREATE_GROUP":
                    self.groups[target] = [sender]
                    self.save_db(self.groups, "groups.json")
                    print(f"[LOG] GROUP CREATED: '{target}' by {sender}")

                elif cmd == "GROUP_MSG":
                    g_name = p["target"]
                    # SECURITY CHECK: Is sender actually in the group?
                    if g_name in self.groups and sender in self.groups[g_name]:
                        print(f"[LOG] Group Msg: {sender} -> '{g_name}'")
                        for member in self.groups[g_name]:
                            if member in self.clients and member != sender:
                                self.clients[member].send(json.dumps(p).encode())
                    else:
                        print(f"[LOG] Blocked: {sender} tried to post to {g_name} without being a member")

                elif cmd == "GET_PUB_KEY":
                    print(f"[LOG] KEY REQUEST: {sender} wants {target}'s public key")
                    key = self.user_db.get(target, {}).get("pub_key")
                    conn.send(json.dumps({"type": "PUB_KEY_RES", "content": key}).encode())

            except Exception as e:
                print(f"[ERROR] Exception in handle_client for {current_user}: {e}")
                break
        
        if current_user and current_user in self.clients:
            print(f"[LOG] USER DISCONNECTED: {current_user}")
            del self.clients[current_user]
        conn.close()

    def run(self):
        while True:
            c, a = self.server.accept()
            threading.Thread(target=self.handle_client, args=(c, a), daemon=True).start()

if __name__ == "__main__":
    ChatServer().run()
