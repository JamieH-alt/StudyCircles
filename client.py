import socket, threading, json, hashlib, base64, time, os
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes

class ChatClient:
    def __init__(self, message_callback=None, start_terminal_listener=True):
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client.connect(('127.0.0.1', 5555))
        self.username = None
        self.callback = message_callback
        self.auth_event = threading.Event()
        self.auth_success = False
        self.pending_pub_key = None
        self.pending_group_pub_keys = None
        self.group_key_event = threading.Event()
        self.key_event = threading.Event()

        # Local History File
        self.history_file = "chat_history.json"
        self.key_file = "private_key.pem"

        # Persistent RSA Setup
        if os.path.exists(self.key_file):
            # Load existing private key from folder
            with open(self.key_file, "rb") as key_file:
                self.private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None
                )
        else:
            # Generate new key if it doesn't exist yet
            self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            # Save it to disk in this client's folder
            pem = self.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            with open(self.key_file, "wb") as f:
                f.write(pem)

        # Derive public key string
        self.public_key_pem = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()
        
        if start_terminal_listener:
            threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self):
        while True:
            try:
                data = self.client.recv(8192).decode()
                if not data: break
                packet = json.loads(data)
                p_type = packet.get("type")

                print("\r" + " " * 50 + "\r", end="") 

                if p_type in ["AUTH_SUCCESS", "AUTH_FAIL"]:
                    self.auth_success = (p_type == "AUTH_SUCCESS")
                    if not self.auth_success: print(f"\n[System] {packet.get('content')}")
                    self.auth_event.set()

                elif p_type == "PUB_KEY_RES":
                    self.pending_pub_key = packet.get("content")
                    self.key_event.set()

                elif p_type == "DIRECT_MSG":
                    decrypted = self.decrypt_msg(packet["content"])
                    # NEW: Silently log received DM locally
                    self._log_message_locally(chat_partner=packet["sender"], sender=packet["sender"], text=decrypted)
                    
                    if self.callback:
                        self.callback(packet["sender"], decrypted)

                elif p_type == "FRIENDS_LIST":
                    friends = packet.get("content", [])
                    print(f"\n[System] Your Friends: {', '.join(friends) if friends else 'None yet'}\n")

                elif p_type == "GROUP_MSG":
                    sender = packet.get("sender")
                    group = packet.get("target")
                    content = packet.get("content")
                    # NEW: Silently log group message locally (stored as plain text since groups aren't E2EE)
                    self._log_message_locally(chat_partner=group, sender=sender, text=content, is_group=True)
                    print(f"\n[{group}] {sender}: {content}")

                elif p_type == "FRIEND_REQUEST":
                    print("e")
                    print(f"\n[System] friend request from {packet.get('content')}")

                elif p_type == "GROUP_INVITE":
                    print(f"\n[System] group invite to {packet.get('content')}")

                elif p_type == "INFO":
                    print(f"{packet}")
                    print(f"\n[System] {packet.get('content')}")

                elif p_type == "INVITES_LIST":
                    invs = packet.get("content", [])
                    print("\n[Pending Invites]:")
                    for i in invs:
                        if i['type'] == 'FRIEND_REQUEST':
                            print(f"- Friend Request from {i['from']}")
                        else:
                            print(f"- Group Invite to {i['group']} (from {i['from']})")

                elif p_type == "GROUPS_LIST":
                    grps = packet.get("content", [])
                    print(f"\n[Your Groups]: {', '.join(grps) if grps else 'None'}")
                    print(f"{self.username}@Chat: ", end="", flush=True)

                elif p_type == "GROUP_PUB_KEYS_RES":
                    self.pending_group_pub_keys = packet.get("content")
                    self.group_key_event.set()

                elif p_type == "GROUP_MSG":
                    sender = packet.get("sender")
                    group = packet.get("target")
                    payloads = packet.get("content", {})
                    
                    # Decrypt only our specific portion of the multi-recipient payload
                    decrypted = "[Decryption Error]"
                    if isinstance(payloads, dict) and self.username in payloads:
                        try:
                            decrypted = self.decrypt_msg(payloads[self.username])
                        except Exception:
                            decrypted = "[Decryption Failed]"
                    else:
                        decrypted = str(payloads)
                        
                    self._log_message_locally(chat_partner=group, sender=sender, text=decrypted, is_group=True)
                    print(f"\n[{group}] {sender}: {decrypted}")

                print(f"{self.username}@Chat: ", end="", flush=True)
    
            except: break

    def auth_action(self, action, username, password):
        self.auth_event.clear()
        packet = {
            "type": action,
            "sender": username,
            "content": hashlib.sha256(password.encode()).hexdigest(),
            "pub_key": self.public_key_pem
        }
        self.client.send(json.dumps(packet).encode())
        self.auth_event.wait(timeout=5)
        if self.auth_success:
            self.username = username
            self.history_file = f"{username}_chat_history.json"
            self.key_file = f"{username}_private_key.pem"
        return self.auth_success

    def get_local_history(self, target_name):
        """Fetches and normalizes saved items into UI-ready tuples."""
        raw_list = self.load_chat_history(target_name)
        # Convert dictionary formats to GUI memory layout: [("Sender", "Text"), ...]
        return [(msg["sender"], msg["content"]) for msg in raw_list]

    def send_dm(self, target, message):
        self.key_event.clear()
        self.client.send(json.dumps({"type": "GET_PUB_KEY", "sender": self.username, "target": target}).encode())
        self.key_event.wait(timeout=2)
        
        if not self.pending_pub_key:
            print(f"[Error] Could not find user {target}")
            return

        # NEW: Log sent DM locally before network transport
        self._log_message_locally(chat_partner=target, sender=self.username, text=message)

        encrypted = self.encrypt_msg(self.pending_pub_key, message)
        packet = {"type": "DIRECT_MSG", "sender": self.username, "target": target, "content": encrypted}
        self.client.send(json.dumps(packet).encode())

    def encrypt_msg(self, pem, msg):
        pub = serialization.load_pem_public_key(pem.encode())
        enc = pub.encrypt(msg.encode(), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        return base64.b64encode(enc).decode()

    def decrypt_msg(self, b64_enc):
        raw = base64.b64decode(b64_enc)
        return self.private_key.decrypt(raw, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)).decode()

    # --- NEW METHODS FOR LOGGING & LOADING HISTORIES ---

    def _log_message_locally(self, chat_partner, sender, text, is_group=False):
        """Helper to encrypt and append messages to a user-specific local JSON database."""
        try:
            # Dynamically reference the logged-in user's history file
            history_path = getattr(self, 'history_file', f"{self.username}_chat_history.json")
            
            db = {}
            if os.path.exists(history_path):
                with open(history_path, "r") as f:
                    db = json.load(f)
                    
            if chat_partner not in db:
                db[chat_partner] = []
                
            if is_group and isinstance(text, dict):
                if self.username in text:
                    text = self.decrypt_msg(text[self.username])
                else:
                    text = "[Encrypted Payload]"
            
            final_content = self.encrypt_msg(self.public_key_pem, text)
                
            db[chat_partner].append({
                "sender": sender,
                "content": final_content,
                "timestamp": time.time(),
                "is_group": is_group
            })
            
            with open(history_path, "w") as f:
                json.dump(db, f, indent=4)
        except Exception as e:
            print(f"\n[Local Log Error] Failed to write history: {e}")

    def load_chat_history(self, chat_partner):
        """Call this from your UI layer to retrieve and decrypt entries for the active user."""
        history_path = getattr(self, 'history_file', f"{self.username}_chat_history.json")
        
        if not os.path.exists(history_path):
            return []
        try:
            with open(history_path, "r") as f:
                db = json.load(f)
            
            history = db.get(chat_partner, [])
            decrypted_history = []
            
            for msg in history:
                try:
                    raw_content = msg["content"]
                    
                    if msg.get("is_group") and (isinstance(raw_content, dict) or not isinstance(raw_content, str) or not raw_content.endswith("==")):
                        if isinstance(raw_content, dict):
                            if self.username in raw_content:
                                text = self.decrypt_msg(raw_content[self.username])
                            else:
                                text = "[Encrypted for other members]"
                        else:
                            text = str(raw_content)
                    else:
                        text = self.decrypt_msg(raw_content)
                        
                    decrypted_history.append({
                        "sender": msg["sender"],
                        "content": text,
                        "timestamp": msg["timestamp"]
                    })
                except Exception:
                    continue
            return decrypted_history
        except Exception:
            return []

    # --- REMAINING METHODS UNCHANGED ---
    def add_friend(self, username):
        self.client.send(json.dumps({"type": "ADD_FRIEND", "sender": self.username, "target": username}).encode())

    def create_group(self, group_name):
        self.client.send(json.dumps({"type": "CREATE_GROUP", "sender": self.username, "target": group_name}).encode())

    def send_group_msg(self, group_name, message):
        self.group_key_event.clear()
        # Query all public keys for members of this group
        self.client.send(json.dumps({"type": "GET_GROUP_PUB_KEYS", "sender": self.username, "target": group_name}).encode())
        self.group_key_event.wait(timeout=3)
        
        if not self.pending_group_pub_keys:
            print(f"[Error] Could not retrieve keys for group {group_name}")
            return
            
        # Encrypt the message text separately for each group member
        encrypted_payloads = {}
        for member, pub_key in self.pending_group_pub_keys.items():
            if pub_key:
                try:
                    encrypted_payloads[member] = self.encrypt_msg(pub_key, message)
                except Exception:
                    continue
                    
        # Log plain text copy to our local file layout
        self._log_message_locally(chat_partner=group_name, sender=self.username, text=message, is_group=True)
        
        packet = {"type": "GROUP_MSG", "sender": self.username, "target": group_name, "content": encrypted_payloads}
        self.client.send(json.dumps(packet).encode())

    def get_friends(self):
        self.client.send(json.dumps({"type": "GET_FRIENDS", "sender": self.username}).encode())

    def add_to_group(self, group_name, friend_name):
        packet = {"type": "ADD_TO_GROUP", "sender": self.username, "target": group_name, "content": friend_name}
        self.client.send(json.dumps(packet).encode())

    def list_invites(self):
        self.client.send(json.dumps({"type": "LIST_INVITES", "sender": self.username}).encode())

    def accept_invite(self, inv_type, name):
        self.client.send(json.dumps({"type": "ACCEPT_INVITE", "sender": self.username, "inv_type": inv_type, "target": name}).encode())

    def list_groups(self):
        self.client.send(json.dumps({"type": "GET_GROUPS", "sender": self.username}).encode())

    def save_received_file(self, filename, b64_content):
        try:
            file_data = base64.b64decode(b64_content)
            save_path = os.path.join(os.getcwd(), f"received_{filename}")
            with open(save_path, "wb") as f:
                f.write(file_data)
            return save_path
        except Exception as e:
            print(f"[Error] Failed to save file: {e}")

# --- TUI RUNNER ---
def on_message(sender, text):
    print(f"\r[{sender}]: {text}\nUser@Chat: ", end="")

if __name__ == "__main__":
    c = ChatClient(message_callback=on_message)
    print("--- School Chat Prototype (Terminal) ---")
    
    mode = input("1. Login / 2. Register: ")
    user = input("User: ")
    pw = input("Pass: ")
    
    action = "LOGIN" if mode == "1" else "REGISTER"
    if c.auth_action(action, user, pw):
        print(f"\nLogged in as {user}.")
        print(f"\n{'='*45}")
        print(f" COMMAND MENU (Logged in as: {c.username})")
        print(f"{'='*45}")
        print(" [CHAT]")
        print("  u:user:msg          -> Private Encrypted Message")
        print("  g:group:msg         -> Group Message")
        print("\n [SOCIAL]")
        print("  add:user            -> Send Friend Request")
        print("  new:group           -> Create a New Group")
        print("  invite:group:user   -> Invite Friend to Group")
        print("\n [MANAGEMENT]")
        print("  invites             -> View Pending Requests")
        print("  accept:friend:user  -> Accept Friend Request")
        print("  accept:group:name   -> Accept Group Invite")
        print("  list:friends        -> View Friend List")
        print("  list:groups         -> View Joined Groups")
        print(f"{'='*45}\n")
        
        while True:
            inp = input(f"{c.username}@Chat: ")
            if not inp: continue
            
            parts = inp.split(":", 2)
            cmd = parts[0].lower()
            

            try:
                if cmd == "u" and len(parts) == 3:
                    c.send_dm(parts[1], parts[2])
                elif cmd == "list":
                    if parts[1] == "friends": c.get_friends()
                    elif parts[1] == "groups": c.list_groups()
                elif cmd == "invite" and len(parts) == 3:
                    c.add_to_group(parts[1], parts[2])
                elif cmd == "g" and len(parts) == 3:
                    c.send_group_msg(parts[1], parts[2])
                elif cmd == "new" and len(parts) == 2:
                    c.create_group(parts[1])
                elif cmd == "add" and len(parts) == 2:
                    c.add_friend(parts[1])
                elif cmd == "invites":
                    c.list_invites()
                elif cmd == "accept":
                    # Format: accept:friend:username OR accept:group:groupname
                    c.accept_invite(parts[1].upper(), parts[2])
                elif cmd == "groups":
                    c.list_groups()
                else:
                    print("Invalid format. Use 'u:target:message' or 'g:group:message'")
            except Exception as e:
                print(f"Error: {e}")
