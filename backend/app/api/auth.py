"""
TG Export - 认证模块
"""
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path
import json
import secrets

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from ..config import settings
from ..models import User, TokenResponse


# 密码加密
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 配置
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

# 用户存储文件
USERS_FILE = settings.DATA_DIR / "users.json"


def hash_password(password: str) -> str:
    """加密密码 (bcrypt 限制最大 72 字节)"""
    # bcrypt 只支持最多 72 字节的密码
    password = password[:72] if len(password.encode('utf-8')) > 72 else password
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    # bcrypt 只支持最多 72 字节的密码
    plain_password = plain_password[:72] if len(plain_password.encode('utf-8')) > 72 else plain_password
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
    return encoded_jwt


def load_users() -> dict:
    """加载用户数据"""
    if not USERS_FILE.exists():
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(users: dict):
    """保存用户数据"""
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def get_user(username: str) -> Optional[User]:
    """获取用户"""
    users = load_users()
    if username in users:
        return User(**users[username])
    return None


def create_user(username: str, password: str) -> User:
    """创建用户"""
    users = load_users()
    user = User(
        username=username,
        password_hash=hash_password(password)
    )
    users[username] = user.model_dump()
    users[username]["created_at"] = user.created_at.isoformat()
    save_users(users)
    return user


def authenticate_user(username: str, password: str) -> Optional[User]:
    """验证用户"""
    user = get_user(username)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def init_admin_user():
    """初始化管理员用户"""
    if not get_user(settings.ADMIN_USERNAME):
        # 如果没有设置密码，生成随机密码
        if not settings.ADMIN_PASSWORD:
            password = secrets.token_urlsafe(12)
            print(f"\n{'='*50}")
            print(f"首次运行，已创建管理员账户")
            print(f"用户名: {settings.ADMIN_USERNAME}")
            print(f"密码: {password}")
            print(f"请妥善保管并及时修改密码！")
            print(f"{'='*50}\n")
        else:
            password = settings.ADMIN_PASSWORD
        
        create_user(settings.ADMIN_USERNAME, password)
        
        # 保存密码到 .env
        env_file = settings.BASE_DIR / ".env"
        with open(env_file, "a", encoding="utf-8") as f:
            f.write(f"\nADMIN_PASSWORD={password}\n")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """获取当前用户"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="认证失败",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = get_user(username)
    if user is None:
        raise credentials_exception
    return user
