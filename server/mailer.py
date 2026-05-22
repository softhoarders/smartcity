import os
import time
import threading
from flask_mail import Mail, Message
from flask import current_app
import config
from models import db, Fine

mail = Mail()

class PhotoMailerWorker(threading.Thread):
    """Background worker to send requested fine photos via email."""
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app
        
    def run(self):
        print("[MAILER] Background worker started.")
        while True:
            try:
                with self.app.app_context():
                    self._process_queue()
            except Exception as e:
                print(f"[MAILER] ERROR: {e}")
            time.sleep(60) # Check every 60 seconds
            
    def _process_queue(self):
        # Find all fines that have a photo requested but not yet sent
        pending_fines = Fine.query.filter_by(photo_requested=True, photo_sent_at=None).all()
        
        for fine in pending_fines:
            # We need the user's email to send it to.
            # Only drivers whose license plate matches the expected plate 
            # should be able to request photos for that spot.
            
            # Since this is a simple system, we just send to the user associated with that spot/plate
            from models import User
            user = User.query.filter_by(license_plate=fine.expected_plate).first()
            
            if not user:
                print(f"[MAILER] Warning: No user found for plate {fine.expected_plate} (Fine #{fine.id})")
                continue
                
            self._send_photo(fine, user.email)

    def _send_photo(self, fine, email):
        print(f"[MAILER] Sending photo for fine #{fine.id} to {email}")
        
        if not fine.image_filename:
             print(f"[MAILER] Error: No image stored for fine #{fine.id}")
             # Mark as sent anyway so we don't keep trying
             fine.photo_sent_at = db.func.now()
             db.session.commit()
             return
             
        filepath = os.path.join(config.UPLOAD_FOLDER, fine.image_filename)
        if not os.path.exists(filepath):
             print(f"[MAILER] Error: Image file not found at {filepath}")
             fine.photo_sent_at = db.func.now()
             db.session.commit()
             return

        # If mail server is set to locahost, use mock mailer
        if config.MAIL_SERVER == "localhost":
            self._mock_send(fine, email, filepath)
        else:
            self._real_send(fine, email, filepath)
            
        fine.photo_sent_at = db.func.now()
        db.session.commit()
        print(f"[MAILER] Completed for fine #{fine.id}")
        
    def _mock_send(self, fine, email, filepath):
        """Simulate sending email by saving it to the MOCK_MAIL_DIR"""
        filename = f"email_fine_{fine.id}_{int(time.time())}.txt"
        out_path = os.path.join(config.MOCK_MAIL_DIR, filename)
        with open(out_path, "w") as f:
            f.write(f"To: {email}\n")
            f.write(f"Subject: ParkScan: Photographic Evidence for Fine #{fine.id}\n")
            f.write(f"Attachment: {os.path.basename(filepath)}\n")
            f.write(f"Message: Attached is the photographic evidence requested.\n")
        print(f"[MAILER-MOCK] Saved mock email to {out_path}")
        
    def _real_send(self, fine, email, filepath):
        """Send a real email using Flask-Mail"""
        msg = Message(
            f"ParkScan: Photographic Evidence for Fine #{fine.id}",
            sender=config.MAIL_DEFAULT_SENDER,
            recipients=[email]
        )
        msg.body = "Attached is the photographic evidence you requested for the parking violation."
        
        with open(filepath, "rb") as f:
            msg.attach(os.path.basename(filepath), "image/jpeg", f.read())
            
        mail.send(msg)
