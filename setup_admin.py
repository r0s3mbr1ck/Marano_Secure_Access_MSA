import secrets
import pyotp

admin_user = input("Admin username: ")
admin_pass = input("Admin password: ")

totp_secret = pyotp.random_base32()

print("\n=== SAVE THIS ===")
print(f"OVPN_ADMIN_USER={admin_user}")
print(f"OVPN_ADMIN_PASS={admin_pass}")
print(f"OVPN_ADMIN_TOTP_SECRET={totp_secret}")

print("\nScan this in Google Authenticator or Other Authenticator App:")
print(pyotp.totp.TOTP(totp_secret).provisioning_uri(
    name=admin_user,
    issuer_name="MSA VPN"
))
