import socket, threading, json, hashlib, base64, time
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes

class ChatClient:
    def __init__(self, message_callback=None):
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client.connect(('127.0.0.1', 5555))
        self.username = None
        self.callback = message_callback
        self.auth_event = threading.Event()
        self.auth_success = False
        self.pending_pub_key = None
        self.key_event = threading.Event()

        # RSA Setup
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_key_pem = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()

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
                    if self.callback:
                        self.callback(packet["sender"], decrypted)

                elif p_type == "FRIENDS_LIST":
                    friends = packet.get("content", [])
                    print(f"\n[System] Your Friends: {', '.join(friends) if friends else 'None yet'}\n")

                elif p_type == "GROUP_MSG":
                    # Group messages aren't usually E2EE in simple prototypes, so we read content directly
                    sender = packet.get("sender")
                    group = packet.get("target")
                    content = packet.get("content")
                    print(f"\n[{group}] {sender}: {content}")

                elif p_type == "INFO":
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

                elif p_type == "FILE_MSG":
                    fname = packet.get("filename")
                    content = packet.get("content")
                    sender = packet.get("sender")
                    
                    path = self.save_received_file(fname, content)
                    print(f"\n[FILE RECEIVED] {sender} sent '{fname}'. Saved to: {path}")
                    print(f"{self.username}@Chat: ", end="", flush=True)
                
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
        if self.auth_success: self.username = username
        return self.auth_success

    def send_dm(self, target, message):
        # 1. Request public key
        self.key_event.clear()
        self.client.send(json.dumps({"type": "GET_PUB_KEY", "sender": self.username, "target": target}).encode())
        self.key_event.wait(timeout=2)
        
        if not self.pending_pub_key:
            print(f"[Error] Could not find user {target}")
            return

        # 2. Encrypt and send
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

    def add_friend(self, username):
        self.client.send(json.dumps({"type": "ADD_FRIEND", "sender": self.username, "target": username}).encode())

    def create_group(self, group_name):
        self.client.send(json.dumps({"type": "CREATE_GROUP", "sender": self.username, "target": group_name}).encode())

    def send_group_msg(self, group_name, message):
        # Group messages are sent as plain text in this prototype
        packet = {"type": "GROUP_MSG", "sender": self.username, "target": group_name, "content": message}
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

    def send_file(self, target, file_path, is_group=False):
        try:
            with open(file_path, "rb") as f:
                file_data = f.read()
                filename = os.path.basename(file_path)
            
            # Encode to Base64 string
            encoded_data = base64.b64encode(file_data).decode()

            packet = {
                "type": "FILE_MSG",
                "sender": self.username,
                "target": target,
                "filename": filename,
                "content": encoded_data,
                "is_encrypted": not is_group
            }

            # If it's a DM, encrypt the Base64 string (Note: RSA has size limits!)
            if not is_group:
                # For large files in a real app, you'd use AES. 
                # For this prototype, we'll send it as is or encrypt if small.
                pass 

            self.client.send(json.dumps(packet).encode())
            print(f"[System] File '{filename}' sent to {target}.")
        except Exception as e:
            print(f"[Error] File send failed: {e}")

    def save_received_file(self, filename, b64_content):
        try:
            file_data = base64.b64decode(b64_content)
            # Save to current directory
            save_path = os.path.join(os.getcwd(), f"received_{filename}")
            with open(save_path, "wb") as f:
                f.read(file_data)
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
                elif cmd == "f" and len(parts) == 3:
                    # Format: f:target_user:path/to/file.txt
                    c.send_file(parts, parts, is_group=False)
                elif cmd == "fg" and len(parts) == 3:
                    # Format: fg:group_name:path/to/file.txt
                    c.send_file(parts, parts, is_group=True)
                else:
                    print("Invalid format. Use 'u:target:message' or 'g:group:message'")
            except Exception as e:
                print(f"Error: {e}")
