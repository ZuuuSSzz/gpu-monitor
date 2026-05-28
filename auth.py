from itsdangerous import TimestampSigner, BadSignature, SignatureExpired
from passlib.hash import bcrypt


class TokenInvalid(Exception):
    pass


def verify_user(username: str, password: str, users: dict[str, str]) -> bool:
    h = users.get(username)
    if not h:
        return False
    try:
        return bcrypt.verify(password, h)
    except (ValueError, TypeError):
        return False


def issue_token(username: str, secret: str) -> str:
    return TimestampSigner(secret).sign(username.encode()).decode()


def verify_token(token: str, secret: str, max_age: int = 60) -> str:
    signer = TimestampSigner(secret)
    try:
        value = signer.unsign(token, max_age=max_age)
        return value.decode()
    except (BadSignature, SignatureExpired) as e:
        raise TokenInvalid(str(e)) from e
