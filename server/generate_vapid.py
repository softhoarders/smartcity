import base64
import ecdsa

def generate_keys():
    # Generate ECDSA curve P-256 key pair
    sk = ecdsa.SigningKey.generate(curve=ecdsa.NIST256p)
    vk = sk.get_verifying_key()
    
    # Export private key in proper format (32 bytes raw -> urlsafe_b64)
    private_key = base64.urlsafe_b64encode(sk.to_string()).decode('utf-8').rstrip('=')
    
    # Export public key in proper format (uncompressed, starting with 0x04)
    public_key_raw = b'\x04' + vk.to_string()
    public_key = base64.urlsafe_b64encode(public_key_raw).decode('utf-8').rstrip('=')
    
    with open(".env", "a") as f:
        f.write(f"\nVAPID_PRIVATE_KEY={private_key}\n")
        f.write(f"VAPID_PUBLIC_KEY={public_key}\n")
        f.write(f"VAPID_SUBJECT=mailto:admin@parkscan.com\n")
    
    print("VAPID keys generated and stored in .env")

if __name__ == "__main__":
    generate_keys()
