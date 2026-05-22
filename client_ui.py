import customtkinter as ctk
from tkinter import messagebox
import threading
import time
import json

# Import the actual background connection client from client.py
from client import ChatClient

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("green")

class StudyCirclesApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("StudyCircles Platform")
        self.geometry("1280x720")
        self.minsize(1100, 600)
        self.resizable(True, True)

        # Muted Sage Palette Configurations
        self.light_green = "#E8F0E8"      
        self.bg_panel = "#F4F7F4"         
        self.dark_green = "#2E4F39"        
        self.accent_green = "#A3BCA9"      
        self.hover_green = "#8EA794"       
        self.highlight_green = "#C2D3C6"   
        self.configure(fg_color=self.light_green)

        # Structural Tracking Dicts
        self.sidebar_buttons = {}
        self.active_conversations = {}  # Format: {"TargetName": [("Sender", "Text"), ...]}
        self.current_target = None
        self.current_target_type = None # "user" or "group"

        # Initialize the client.py core and inject custom GUI interceptor logic
        self.backend = ChatClient(message_callback=self._handle_inbound_dm)
        self._hijack_backend_listener()

        # Build Primary Window Frames
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.create_login_screen()
        self.create_message_screen()
        self.show_login_screen()

    # --- INBOUND NETWORK INTERCEPTORS ---

    def _hijack_backend_listener(self):
        """Wraps text handlers to route data to UI queues instead of print lines."""
        def intercepted_listen():
            while True:
                try:
                    data = self.backend.client.recv(8192).decode()
                    if not data: 
                        break
                    
                    packet = json.loads(data)
                    p_type = packet.get("type")

                    if p_type in ["AUTH_SUCCESS", "AUTH_FAIL"]:
                        self.backend.auth_success = (p_type == "AUTH_SUCCESS")
                        self.backend.auth_event.set()

                    elif p_type == "PUB_KEY_RES":
                        self.backend.pending_pub_key = packet.get("content")
                        self.backend.key_event.set()

                    elif p_type == "DIRECT_MSG":
                        decrypted = self.backend.decrypt_msg(packet["content"])
                        self._handle_inbound_dm(packet["sender"], decrypted)

                    elif p_type == "GROUP_MSG":
                        self._handle_inbound_group_msg(packet.get("target"), packet.get("sender"), packet.get("content"))

                    elif p_type == "FRIENDS_LIST":
                        friends = packet.get("content", [])
                        self.after(1, lambda: self._update_conversations_list(friends, "user"))

                    elif p_type == "GROUPS_LIST":
                        groups = packet.get("content", [])
                        self.after(1, lambda: self._update_conversations_list(groups, "group"))

                    elif p_type == "INVITES_LIST":
                        invites_content = packet.get("content", [])
                        self.after(1, lambda: self._populate_incoming_invites_panel(invites_content))

                    elif p_type == "INFO":
                        self.trigger_manual_refresh()

                except Exception as e: 
                    print(f"[UI Monitor Debug] Stream disconnected: {e}")
                    break

        self.backend.client.settimeout(None) 
        threading.Thread(target=intercepted_listen, daemon=True).start()

    def _handle_inbound_dm(self, sender, text):
        """Processes and appends direct messages into local storage dictionaries thread-safely."""
        if sender not in self.active_conversations:
            self.active_conversations[sender] = []
        self.active_conversations[sender].append((sender, text))
        
        if self.current_target == sender:
            self.after(1, lambda: self._render_msg_line(sender, text))

    def _handle_inbound_group_msg(self, group_name, sender, text):
        """Processes and appends incoming room conversations thread-safely."""
        if group_name not in self.active_conversations:
            self.active_conversations[group_name] = []
        self.active_conversations[group_name].append((sender, text))
        
        if self.current_target == group_name:
            self.after(1, lambda: self._render_msg_line(sender, text))

    # --- SCREEN DRAW CREATION ---

    def create_login_screen(self):
        self.login_frame = ctk.CTkFrame(self, fg_color=self.light_green)
        card = ctk.CTkFrame(self.login_frame, width=400, height=480, fg_color="white", corner_radius=15)
        card.place(relx=0.5, rely=0.5, anchor="center")
        card.grid_propagate(False)

        label = ctk.CTkLabel(card, text="StudyCircles Portal", font=("Arial", 26, "bold"), text_color=self.dark_green)
        label.pack(pady=(40, 20))

        self.auth_mode = ctk.StringVar(value="LOGIN")
        mode_toggle = ctk.CTkSegmentedButton(card, values=["LOGIN", "REGISTER"], variable=self.auth_mode, selected_color=self.accent_green)
        mode_toggle.pack(pady=10, padx=50, fill="x")

        self.username_entry = ctk.CTkEntry(card, placeholder_text="Username", width=300, height=40)
        self.username_entry.pack(pady=15)

        self.password_entry = ctk.CTkEntry(card, placeholder_text="Password", show="*", width=300, height=40)
        self.password_entry.pack(pady=15)

        login_btn = ctk.CTkButton(card, text="Submit Request", font=("Arial", 16, "bold"), fg_color=self.accent_green, hover_color=self.hover_green, text_color=self.dark_green, width=300, height=45, command=self.handle_login_action)
        login_btn.pack(pady=30)

    def create_message_screen(self):
        self.message_frame = ctk.CTkFrame(self, fg_color=self.light_green)
        
        # FIXED: Removed minsize constraints to prevent window clipping bugs
        self.message_frame.grid_columnconfigure(0, weight=1) 
        self.message_frame.grid_columnconfigure(1, weight=3)              
        self.message_frame.grid_rowconfigure(0, weight=1)

        # LEFT SIDEBAR FRAME
        sidebar = ctk.CTkFrame(self.message_frame, fg_color="white", corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 1))
        
        sidebar.grid_rowconfigure(3, weight=1) 
        sidebar.grid_columnconfigure(0, weight=1)

        self.profile_lbl = ctk.CTkLabel(sidebar, text="🟢 Online", font=("Arial", 15, "bold"), text_color=self.dark_green)
        self.profile_lbl.grid(row=0, column=0, pady=20, padx=20, sticky="w")

        self.btn_invites_menu = ctk.CTkButton(sidebar, text="📩 Invites & Requests", height=40, font=("Arial", 13, "bold"), fg_color=self.accent_green, hover_color=self.hover_green, text_color=self.dark_green, command=self.show_invites_view)
        self.btn_invites_menu.grid(row=1, column=0, pady=5, padx=15, sticky="ew")

        btn_new_group = ctk.CTkButton(sidebar, text="➕ Create Group", height=40, font=("Arial", 13, "bold"), fg_color=self.accent_green, hover_color=self.hover_green, text_color=self.dark_green, command=self.create_group_dialog)
        btn_new_group.grid(row=2, column=0, pady=5, padx=15, sticky="ew")

        self.chat_list_scroll = ctk.CTkScrollableFrame(sidebar, label_text="Conversations Channels", label_text_color=self.dark_green, fg_color="transparent")
        self.chat_list_scroll.grid(row=3, column=0, pady=15, padx=10, sticky="nsew")

        btn_logout = ctk.CTkButton(sidebar, text="Disconnect", fg_color="#E0E6E1", text_color="#555555", hover_color="#D0D6D1", command=self.quit)
        btn_logout.grid(row=4, column=0, pady=20, padx=15, sticky="ew")

        # RIGHT PANELS CONTAINER
        self.content_container = ctk.CTkFrame(self.message_frame, fg_color=self.bg_panel, corner_radius=0)
        self.content_container.grid(row=0, column=1, sticky="nsew")
        
        self.build_chat_view()
        self.build_invites_view()

    def build_chat_view(self):
        self.chat_view_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.chat_view_frame.grid_rowconfigure(1, weight=1)
        self.chat_view_frame.grid_columnconfigure(0, weight=1)

        self.chat_title_lbl = ctk.CTkLabel(self.chat_view_frame, text="Select a contact to begin streaming messages", font=("Arial", 18, "bold"), text_color=self.dark_green)
        self.chat_title_lbl.grid(row=0, column=0, sticky="w", padx=30, pady=20)

        self.chat_box = ctk.CTkTextbox(self.chat_view_frame, font=("Arial", 14), fg_color="white", text_color="#333333", border_width=1, border_color="#E0E0E0")
        self.chat_box.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 20))
        self.chat_box.configure(state="disabled")

        input_row = ctk.CTkFrame(self.chat_view_frame, fg_color="transparent")
        input_row.grid(row=2, column=0, sticky="ew", padx=30, pady=(0, 30))
        input_row.grid_columnconfigure(0, weight=1)

        self.msg_entry = ctk.CTkEntry(input_row, placeholder_text="Type your secure encrypted message payload...", height=45)
        self.msg_entry.grid(row=0, column=0, sticky="ew", padx=(0, 15))

        send_btn = ctk.CTkButton(input_row, text="Send Payload", width=140, height=45, font=("Arial", 13, "bold"), fg_color=self.accent_green, hover_color=self.hover_green, text_color=self.dark_green, command=self.send_message_hook)
        send_btn.grid(row=0, column=1)

    def build_invites_view(self):
        self.invites_view_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.invites_view_frame.grid_columnconfigure(0, weight=1)
        self.invites_view_frame.grid_columnconfigure(1, weight=1)
        self.invites_view_frame.grid_rowconfigure(1, weight=1)

        # Left Column Title Bar Configuration Layout
        left_title_frame = ctk.CTkFrame(self.invites_view_frame, fg_color="transparent")
        left_title_frame.grid(row=0, column=0, sticky="ew", padx=30, pady=20)
        
        lbl_left = ctk.CTkLabel(left_title_frame, text="Incoming Inbox Requests", font=("Arial", 18, "bold"), text_color=self.dark_green)
        lbl_left.pack(side="left")

        # FIXED: Removed wrapper bounds clipping layout bugs so button shows up completely
        btn_refresh = ctk.CTkButton(left_title_frame, text="🔄 Refresh Data", width=110, height=28, font=("Arial", 11, "bold"), fg_color=self.accent_green, hover_color=self.hover_green, text_color=self.dark_green, command=self.trigger_manual_refresh)
        btn_refresh.pack(side="right", padx=(20, 0))

        lbl_right = ctk.CTkLabel(self.invites_view_frame, text="Dispatch Outbound Invitations", font=("Arial", 18, "bold"), text_color=self.dark_green)
        lbl_right.grid(row=0, column=1, sticky="w", padx=30, pady=20)

        self.scroll_invites = ctk.CTkScrollableFrame(self.invites_view_frame, fg_color="white", border_width=1, border_color="#E0E0E0")
        self.scroll_invites.grid(row=1, column=0, sticky="nsew", padx=(30, 15), pady=(0, 30))

        send_panel = ctk.CTkFrame(self.invites_view_frame, fg_color="white", border_width=1, border_color="#E0E0E0", corner_radius=8)
        send_panel.grid(row=1, column=1, sticky="nsew", padx=(15, 30), pady=(0, 30))
        
        self.form_container = ctk.CTkFrame(send_panel, fg_color="transparent")
        self.form_container.pack(fill="both", expand=True, padx=40, pady=40)

        self.lbl_type = ctk.CTkLabel(self.form_container, text="Transaction Request Type:", font=("Arial", 13, "bold"), text_color=self.dark_green)
        self.lbl_type.pack(anchor="w", pady=(0, 5))

        self.invite_type_var = ctk.StringVar(value="Friend Request")
        dropdown = ctk.CTkOptionMenu(
            self.form_container, values=["Friend Request", "Group Chat Invite"], 
            variable=self.invite_type_var, height=38,
            fg_color=self.accent_green, button_color=self.accent_green, button_hover_color=self.hover_green, text_color=self.dark_green,
            command=self._toggle_outbound_form_fields
        )
        dropdown.pack(fill="x", pady=(0, 20))

        self.lbl_target = ctk.CTkLabel(self.form_container, text="Target Recipient Username:", font=("Arial", 13, "bold"), text_color=self.dark_green)
        self.lbl_target.pack(anchor="w", pady=(0, 5))
        
        self.invite_target_entry = ctk.CTkEntry(self.form_container, placeholder_text="Type friend username here...", height=40)
        self.invite_target_entry.pack(fill="x", pady=(0, 20))

        self.group_field_frame = ctk.CTkFrame(self.form_container, fg_color="transparent")
        
        lbl_group_select = ctk.CTkLabel(self.group_field_frame, text="Target Group Name Context:", font=("Arial", 13, "bold"), text_color=self.dark_green)
        lbl_group_select.pack(anchor="w", pady=(0, 5))
        
        self.invite_group_entry = ctk.CTkEntry(self.group_field_frame, placeholder_text="Type existing group name here...", height=40)
        self.invite_group_entry.pack(fill="x", pady=(0, 20))

        btn_send_invite = ctk.CTkButton(self.form_container, text="Transmit Request Payload", height=45, font=("Arial", 13, "bold"), fg_color=self.dark_green, text_color="white", command=self.send_invite_hook)
        btn_send_invite.pack(fill="x", side="bottom", pady=(20, 0))

    def _toggle_outbound_form_fields(self, selected_mode):
        """Dynamically switches entry fields when form constraints toggle."""
        if selected_mode == "Group Chat Invite":
            self.group_field_frame.pack(fill="x", after=self.invite_target_entry)
            self.lbl_target.configure(text="Friend to Invite (Username):")
        else:
            self.group_field_frame.pack_forget()
            self.lbl_target.configure(text="Target Recipient Username:")

    # --- DYNAMIC REPAINT ELEMENTS ---

    def _update_conversations_list(self, items_list, item_type):
        """Clears old sidebar nodes and recreates widgets safely."""
        prefix_check = "👤 " if item_type == "user" else "👥 "
        
        # Clean up keys for this specific channel type
        for key in list(self.sidebar_buttons.keys()):
            if key.startswith(prefix_check):
                try:
                    self.sidebar_buttons[key].destroy()
                    del self.sidebar_buttons[key]
                except:
                    pass

        # Repaint updated values list
        for item in items_list:
            if not item: continue
            display_str = f"{prefix_check}{item}"
            btn = ctk.CTkButton(
                self.chat_list_scroll, text=display_str,
                fg_color="transparent", text_color="#444444", hover_color="#EAEAEA", anchor="w", height=45,
                command=lambda name=item, t=item_type: self.open_chat_hook(name, t)
            )
            btn.pack(fill="x", pady=2, padx=5)
            self.sidebar_buttons[display_str] = btn

    def _populate_incoming_invites_panel(self, payload_list):
        """Iterates and builds interactable accept layouts for pending items inside the scrollview safely."""
        for child in self.scroll_invites.winfo_children():
            child.destroy()

        if not payload_list or not isinstance(payload_list, list):
            lbl_empty = ctk.CTkLabel(self.scroll_invites, text="No pending invitations found.", font=("Arial", 13, "italic"), text_color="grey")
            lbl_empty.pack(pady=20)
            return

        for item in payload_list:
            if not isinstance(item, dict): 
                continue
                
            row_frame = ctk.CTkFrame(self.scroll_invites, fg_color="#FAF9F6", height=55, corner_radius=6)
            row_frame.pack(fill="x", pady=4, padx=5)
            row_frame.pack_propagate(False)

            # FIXED: Bulletproof casing validation matching your exact server file dictionary parameters
            is_friend_req = item.get('type') == 'FRIEND_REQUEST'
            sender_id = item.get('from', 'Unknown')
            group_id = item.get('group', 'Unknown')

            display_text = f"Friend Req from {sender_id}" if is_friend_req else f"Group invite to {group_id} ({sender_id})"
            
            lbl = ctk.CTkLabel(row_frame, text=display_text, font=("Arial", 12), text_color="#333333")
            lbl.pack(side="left", padx=15)

            inv_type_arg = "FRIEND" if is_friend_req else "GROUP"
            target_name_arg = sender_id if is_friend_req else group_id

            btn_accept = ctk.CTkButton(
                row_frame, text="Accept / Join", width=90, height=30, font=("Arial", 11, "bold"),
                fg_color=self.accent_green, hover_color=self.hover_green, text_color=self.dark_green,
                command=lambda t=inv_type_arg, n=target_name_arg, f=row_frame: self.accept_invite_hook(t, n, f)
            )
            btn_accept.pack(side="right", padx=10, pady=12)

    def highlight_sidebar_selection(self, selected_item, selected_type=None):
        """Updates background colors to match focus choices."""
        target_prefix = "👤 " if selected_type == "user" else "👥 "
        target_key = f"{target_prefix}{selected_item}" if selected_type else None

        for key, button in self.sidebar_buttons.items():
            if key == target_key:
                button.configure(fg_color=self.highlight_green, text_color=self.dark_green, font=("Arial", 13, "bold"))
            else:
                button.configure(fg_color="transparent", text_color="#444444", font=("Arial", 13))
        
        self.btn_invites_menu.configure(
            fg_color=self.highlight_green if selected_item == "__invites_menu__" else self.accent_green,
            text_color=self.dark_green
        )

    # --- CORE PANEL TOGGLES ---

    def show_login_screen(self):
        self.message_frame.pack_forget()
        self.login_frame.pack(fill="both", expand=True)

    def show_message_screen(self):
        self.profile_lbl.configure(text=f"🟢 {self.backend.username}")
        self.login_frame.pack_forget()
        
        # FIXED: Lock structural layouts so sidebar dimensions stay uniform
        self.message_frame.pack(fill="both", expand=True)
        self.show_invites_view()
        
        # FIXED: Forces an automatic background loop fetch instantly upon successful login
        self.trigger_manual_refresh()

    def show_chat_view(self):
        self.invites_view_frame.pack_forget()
        self.chat_view_frame.pack(fill="both", expand=True)

    def show_invites_view(self):
        self.highlight_sidebar_selection("__invites_menu__")
        self.chat_view_frame.pack_forget()
        self.invites_view_frame.pack(fill="both", expand=True)
        
        def async_fetch_invites():
            try:
                self.backend.list_invites()
            except:
                pass
        threading.Thread(target=async_fetch_invites, daemon=True).start()

    def trigger_manual_refresh(self):
        """Dispatches an asynchronous timed loop to query and rebuild client channels."""
        def async_refresh():
            try:
                self.backend.list_invites()
                time.sleep(0.15)
                self.backend.get_friends()
                time.sleep(0.15)
                self.backend.list_groups()
            except Exception as e:
                print(f"[UI Sync Error] Failed manual data list update query: {e}")
        threading.Thread(target=async_refresh, daemon=True).start()

    def create_group_dialog(self):
        dialog = ctk.CTkInputDialog(text="Enter unique name layout for New Group room channel:", title="Create Group Workspace")
        dialog.configure(fg_color=self.light_green)
        group_name = dialog.get_input()
        if group_name and group_name.strip():
            def async_group_creation():
                try:
                    self.backend.create_group(group_name.strip())
                    time.sleep(0.3)
                    self.backend.list_groups()
                except Exception as e:
                    print(f"[UI System Fault] Failed to run async room channel allocation: {e}")
            threading.Thread(target=async_group_creation, daemon=True).start()

    # --- FUNCTION HOOK INTERFACE EXECUTORS ---

    def handle_login_action(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        action_mode = self.auth_mode.get()

        if not username or not password:
            messagebox.showerror("Validation Error", "Inputs cannot stand completely empty.")
            return

        def async_auth():
            try:
                success = self.backend.auth_action(action_mode, username, password)
                if success:
                    self.after(1, self.show_message_screen)
                else:
                    self.after(1, lambda: messagebox.showerror("Server Auth Fault", f"Action {action_mode} rejected by remote server."))
            except Exception as e:
                self.after(1, lambda: messagebox.showerror("Network Drop", f"Connection lost during authentication:\n{e}"))

        threading.Thread(target=async_auth, daemon=True).start()

    def open_chat_hook(self, target_name, target_type):
        self.current_target = target_name
        self.current_target_type = target_type
        self.highlight_sidebar_selection(target_name, target_type)
        self.show_chat_view()
        
        prefix_title = "Direct Secure E2EE Conversation with" if target_type == "user" else "Public Shared Room Group Workspace"
        self.chat_title_lbl.configure(text=f"{prefix_title}: {target_name}")
        
        self.chat_box.configure(state="normal")
        self.chat_box.delete("1.0", ctk.END)
        
        if target_name in self.active_conversations:
            for sender, message_content in self.active_conversations[target_name]:
                self.chat_box.insert(ctk.END, f"[{sender}]: {message_content}\n")
                
        self.chat_box.configure(state="disabled")
        self.chat_box.see(ctk.END)

    def _render_msg_line(self, sender, text):
        """Appends text content into history box view instantly."""
        self.chat_box.configure(state="normal")
        self.chat_box.insert(ctk.END, f"[{sender}]: {text}\n")
        self.chat_box.configure(state="disabled")
        self.chat_box.see(ctk.END)

    def send_message_hook(self):
        message = self.msg_entry.get().strip()
        if not message or not self.current_target: return

        if self.current_target_type == "group":
            self._handle_inbound_group_msg(self.current_target, self.backend.username, message)

        def async_outbound_dispatch():
            try:
                if self.current_target_type == "user":
                    self.backend.send_dm(self.current_target, message)
                    self.after(1, lambda: self._handle_inbound_dm(self.backend.username, message))
                else:
                    self.backend.send_group_msg(self.current_target, message)
            except Exception as e:
                self.after(1, lambda: messagebox.showerror("Network Error", f"Failed to send message payload:\n{e}"))

        threading.Thread(target=async_outbound_dispatch, daemon=True).start()
        self.msg_entry.delete(0, ctk.END)

    def accept_invite_hook(self, inv_type, name, row_frame):
        try:
            row_frame.destroy()
        except:
            pass

        def async_accept():
            try:
                self.backend.accept_invite(inv_type, name)
                time.sleep(0.3)
                self.trigger_manual_refresh()
            except Exception as e:
                print(f"[UI System Fault] Drop during invitation acceptance sequence: {e}")
        
        threading.Thread(target=async_accept, daemon=True).start()

    def send_invite_hook(self):
        target_friend = self.invite_target_entry.get().strip()
        invite_type = self.invite_type_var.get()
        
        if not target_friend: 
            return

        def async_send_invite():
            try:
                if invite_type == "Friend Request":
                    self.backend.add_friend(target_friend)
                    self.after(1, lambda: messagebox.showinfo("Dispatched", f"Sent friend invite payload out to {target_friend}"))
                else:
                    target_group = self.invite_group_entry.get().strip()
                    if not target_group:
                        self.after(1, lambda: messagebox.showwarning("Validation Error", "Target Group field cannot stand empty."))
                        return
                    
                    self.backend.add_to_group(target_group, target_friend)
                    self.after(1, lambda: messagebox.showinfo("Dispatched", f"Invited {target_friend} to group: {target_group}"))
                
                time.sleep(0.3)
                self.trigger_manual_refresh()
            except Exception as e:
                self.after(1, lambda: messagebox.showerror("Connection Error", f"Server dropped transaction:\n{e}"))

        threading.Thread(target=async_send_invite, daemon=True).start()
        self.invite_target_entry.delete(0, ctk.END)
        self.invite_group_entry.delete(0, ctk.END)


if __name__ == "__main__":
    app = StudyCirclesApp()
    app.mainloop()
