"""
TG Export - Telegram 客户端
使用 Pyrogram 异步库连接 Telegram
"""
import asyncio
import os
import logging
import base64
import secrets
import time
from pathlib import Path
from typing import Optional, List, AsyncGenerator, Union, Dict, Any
from pyrogram import Client
from pyrogram.handlers import RawUpdateHandler
from pyrogram import raw
from pyrogram.session import Session
from pyrogram.session.auth import Auth
from pyrogram.utils import compute_password_check
from pyrogram.types import Chat, Message, Dialog
from pyrogram.enums import ChatType as PyChatType
from pyrogram.errors import (
    SessionPasswordNeeded, FloodWait, PhoneCodeInvalid, 
    PhoneCodeExpired, PhoneNumberInvalid, Unauthorized,
    UserDeactivated
)

from ..config import settings
from ..models import ChatInfo, ChatType, MessageInfo, MediaType

logger = logging.getLogger(__name__)

class TelegramClient:
    """Telegram 客户端封装"""
    
    def __init__(self):
        self._client: Optional[Client] = None
        self._is_authorized = False
        self._peers_warmed = False # 是否已预热对话缓存 (v2.4.2)
        self._api_id: Optional[int] = None
        self._api_hash: Optional[str] = None
        self._phone: Optional[str] = None
        self._phone_code_hash: Optional[str] = None
        self._lock = asyncio.Lock() # 用于保护连接和初始化过程
        self._message_cache = {} # { (chat_id, msg_id): (message_obj, timestamp) }
        self._me_cache = None    # 缓存 get_me 结果
        self._me_cache_time = 0  # 缓存时间戳
        self._cache_lock = asyncio.Lock()
        self._qr_login_tokens: Dict[str, Dict[str, Any]] = {}
        self._qr_password_session: Optional[Session] = None
        self._qr_password_dc_id: Optional[int] = None
        self._qr_login_event = asyncio.Event()
        self._raw_update_handler_registered = False

    async def _close_qr_password_session(self):
        if self._qr_password_session:
            try:
                await self._qr_password_session.stop()
            except Exception:
                pass
        self._qr_password_session = None
        self._qr_password_dc_id = None

    async def _on_raw_update(self, client, update, users, chats):
        try:
            if isinstance(update, raw.types.UpdateLoginToken):
                logger.info("[TG][QR] received UpdateLoginToken")
                self._qr_login_event.set()
        except Exception as e:
            logger.warning("[TG][QR] raw update handler error: %s", e)

    async def _ensure_raw_update_handler(self):
        if self._client and not self._raw_update_handler_registered:
            self._client.add_handler(RawUpdateHandler(self._on_raw_update), group=-999)
            self._raw_update_handler_registered = True

        if self._client:
            worker_tasks = getattr(self._client.dispatcher, "handler_worker_tasks", None) or []
            alive = any(not t.done() for t in worker_tasks)
            if not alive:
                await self._client.dispatcher.start()
                logger.info("[TG][QR] dispatcher workers started for raw updates")

    async def _switch_client_to_dc(self, dc_id: int):
        """参考现成 Pyrogram QR 登录实现：确保会话切到 nearest/auth DC 再导出二维码 token。"""
        if not self._client:
            raise RuntimeError("客户端未初始化")
        try:
            if getattr(self._client, "session", None):
                await self._client.session.stop()
        except Exception:
            pass
        await self._client.storage.dc_id(dc_id)
        await self._client.storage.auth_key(
            await Auth(
                self._client,
                await self._client.storage.dc_id(),
                await self._client.storage.test_mode()
            ).create()
        )
        self._client.session = Session(
            self._client,
            await self._client.storage.dc_id(),
            await self._client.storage.auth_key(),
            await self._client.storage.test_mode()
        )
        await self._client.session.start()
        logger.info("[TG][QR] switched client session to dc_id=%s", dc_id)

    async def _ensure_nearest_dc_for_qr(self):
        if not self._client:
            raise RuntimeError("客户端未初始化")
        nearest = await self._client.invoke(raw.functions.help.GetNearestDc())
        current_dc = await self._client.storage.dc_id()
        target_dc = getattr(nearest, "nearest_dc", None) or current_dc
        logger.info("[TG][QR] current_dc=%s nearest_dc=%s this_dc=%s", current_dc, getattr(nearest, "nearest_dc", None), getattr(nearest, "this_dc", None))
        if target_dc and target_dc != current_dc:
            await self._switch_client_to_dc(int(target_dc))

    async def _sync_auth_from_session(self, session: Session):
        """将已授权的 QR 会话授权导入主会话，确保后续统一使用 self._client。"""
        if not self._client:
            raise RuntimeError("客户端未初始化")
        main_dc = await self._client.storage.dc_id()
        exported = await session.invoke(
            raw.functions.auth.ExportAuthorization(dc_id=main_dc)
        )
        imported = await self._client.invoke(
            raw.functions.auth.ImportAuthorization(id=exported.id, bytes=exported.bytes)
        )
        if getattr(imported, "user", None):
            await self._client.storage.user_id(imported.user.id)
            await self._client.storage.is_bot(False)

    async def _adopt_session_as_main(self, session: Session, user_id: int):
        """将指定 Session 的 DC/AuthKey 接管到主客户端，避免 USER_MIGRATE 卡住。"""
        if not self._client:
            raise RuntimeError("客户端未初始化")

        api_id = int(self._api_id or 0)
        api_hash = str(self._api_hash or "")

        # 关闭旧主客户端；Pyrogram disconnect() 会顺带关闭 storage，所以后面必须重建 client。
        try:
            if self._client.is_connected:
                await self._client.disconnect()
        except Exception:
            pass

        self._client = None
        self._is_authorized = False
        await self.init(api_id, api_hash)
        if not self._client:
            raise RuntimeError("主客户端重建失败")

        # 注意：这里不能先 connect 再覆盖 auth_key；直接写 storage 后再 connect。
        await self._client.storage.open()
        await self._client.storage.dc_id(session.dc_id)
        await self._client.storage.auth_key(session.auth_key)
        await self._client.storage.user_id(user_id)
        await self._client.storage.is_bot(False)
        await self._client.storage.save()
        await self._client.storage.close()

        # 丢弃刚才已关闭 storage 的 client，再新建一次，让 Pyrogram 从 session 文件重新加载。
        self._client = None
        await self.init(api_id, api_hash)
        await self._ensure_connected()

    async def _mark_session_authorized(self) -> Dict[str, Any]:
        """统一标记会话为已登录，确保扫码与手机号登录都能持久复用会话。"""
        if not self._client:
            raise RuntimeError("客户端未初始化")
        me = await self._client.get_me()
        await self._client.storage.user_id(me.id)
        await self._client.storage.is_bot(False)
        self._is_authorized = True
        user_info = {
            "id": me.id,
            "first_name": me.first_name,
            "last_name": me.last_name,
            "username": me.username,
            "phone": me.phone_number
        }
        self._me_cache = user_info
        self._me_cache_time = time.time()
        return user_info
    
    @property
    def is_authorized(self) -> bool:
        return self._is_authorized
    
    @property
    def is_initialized(self) -> bool:
        return self._client is not None
    
    def _check_ipv6_support(self) -> bool:
        """检测系统是否支持 IPv6 连接到 Telegram"""
        import socket
        
        # Telegram IPv6 服务器地址 (DC2)
        telegram_ipv6_hosts = [
            ("2001:67c:4e8:f002::a", 443),  # DC2 IPv6
            ("2001:67c:4e8:f003::a", 443),  # DC3 IPv6
        ]
        
        for host, port in telegram_ipv6_hosts:
            try:
                sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect((host, port))
                sock.close()
                print(f"[TG] IPv6 连接测试成功: {host}")
                return True
            except (socket.error, OSError) as e:
                print(f"[TG] IPv6 连接测试失败 ({host}): {e}")
                continue
        
        return False
    
    async def init(self, api_id: int, api_hash: str, session_name: str = "tg_export"):
        """初始化客户端（只创建实例，不连接）"""
        async with self._lock:
            # 如果配置没变且已初始化，则无需重新创建
            if self._client and self._api_id == api_id and self._api_hash == api_hash:
                print(f"[TG] API 配置未变，跳过初始化")
                return

            # 保存凭证
            self._api_id = api_id
            self._api_hash = api_hash
            
            # 清理旧客户端
            if self._client:
                try:
                    if self._client.is_connected:
                        await self._client.disconnect()
                except:
                    pass
                self._client = None
            
            settings.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
            
            # IPv6 自动检测与回退
            use_ipv6 = settings.USE_IPV6
            if use_ipv6:
                use_ipv6 = self._check_ipv6_support()
                if not use_ipv6:
                    print("[TG] IPv6 不可用，自动切换到 IPv4")
            
            self._client = Client(
                name=session_name,
                api_id=api_id,
                api_hash=api_hash,
                workdir=str(settings.SESSIONS_DIR),
                device_model="TG Export Web",
                system_version="Linux",
                ipv6=use_ipv6,  # IPv6 支持 (自动检测)
                sleep_threshold=0, # [Fast Response] 禁用内置自动等待，让异常立即抛出
                workers=100, # [FIX] 提升内部线程数，处理更高并发 (v1.6.5 自动化)
                max_concurrent_transmissions=10  # [FIX v1.3.9] 关键参数：允许最多 10 个并发传输
            )
            print(f"[TG] 客户端已初始化: api_id={api_id}, ipv6={use_ipv6}")
    
    async def _ensure_connected(self):
        """确保客户端已连接"""
        if not self._client:
            raise RuntimeError("客户端未初始化，请先配置 API ID 和 API Hash")
        
        if not self._client.is_connected:
            async with self._lock:
                # 双重检查模式，防止重复连接
                if not self._client.is_connected:
                    print("[TG] 正在连接...")
                    try:
                        await self._client.connect()
                        print("[TG] 已连接")
                    except Exception as e:
                        print(f"[TG] 连接异常: {e}")
                        raise

    def set_max_concurrent_transmissions(self, value: int):
        """动态设置最大并发传输数 (v1.4.0)
        
        允许用户通过 Web UI 配置的 max_concurrent_downloads 生效。
        Pyrogram 的 Client 对象在运行时支持修改此属性。
        """
        if self._client:
            # [FIX] 确保并发传输数不超过内部 workers 数，防止 Pyrogram 内部死锁
            safe_value = min(value, self._client.workers)
            self._client.max_concurrent_transmissions = safe_value
            print(f"[TG] 已设置最大并发传输数: {safe_value} (原始请求: {value})")
        else:
            print(f"[TG] 警告: 客户端未初始化，无法设置并发数")
    
    async def send_code(self, phone: str) -> str:
        """发送验证码"""
        await self._ensure_connected()
        
        self._phone = phone
        print(f"[TG] 发送验证码到 {phone}...")
        
        try:
            sent_code = await self._client.send_code(phone)
            self._phone_code_hash = sent_code.phone_code_hash
            print(f"[TG] 验证码已发送，hash: {self._phone_code_hash[:10]}...")
            return self._phone_code_hash
        except FloodWait as e:
            print(f"[TG] 需要等待 {e.value} 秒后再操作")
            raise RuntimeError(f"请求过于频繁，请等待 {e.value} 秒后再试")
        except PhoneNumberInvalid:
            raise RuntimeError("手机号码无效")
        except Exception as e:
            print(f"[TG] 发送验证码失败: {e}")
            raise
    
    async def sign_in(self, phone: str, code: str, phone_code_hash: str, password: str = None) -> bool:
        """登录验证"""
        await self._ensure_connected()
        
        try:
            if password:
                # 两步验证
                print(f"[TG] 使用两步验证密码登录...")
                await self._client.check_password(password)
            else:
                # 验证码登录
                print(f"[TG] 使用验证码登录: {code}")
                await self._client.sign_in(phone, phone_code_hash, code)
            
            self._is_authorized = True
            print("[TG] 登录成功!")
            return True
            
        except SessionPasswordNeeded:
            print("[TG] 需要两步验证密码")
            raise RuntimeError("需要两步验证密码 (2FA)")
        except PhoneCodeInvalid:
            raise RuntimeError("验证码错误")
        except PhoneCodeExpired:
            raise RuntimeError("验证码已过期")
        except FloodWait as e:
            raise RuntimeError(f"请等待 {e.value} 秒后再尝试登录")
        except Exception as e:
            print(f"[TG] 登录失败: {e}")
            raise

    async def verify_2fa_password(self, password: str) -> Dict[str, Any]:
        """为二维码登录流程提交两步验证密码"""
        await self._ensure_connected()
        if not self._client:
            raise RuntimeError("客户端未初始化")
        try:
            logger.info("[TG][QR] verify_2fa_password start")
            if not self._qr_password_session:
                prep = await self._prepare_qr_password_session()
                if prep.get("status") == "authorized":
                    self._qr_login_tokens.clear()
                    return prep
            if self._qr_password_session:
                pwd = await self._qr_password_session.invoke(raw.functions.account.GetPassword())
                auth = await self._qr_password_session.invoke(
                    raw.functions.auth.CheckPassword(
                        password=compute_password_check(pwd, password)
                    )
                )
                user_id = getattr(getattr(auth, "user", None), "id", None)
                if not user_id:
                    raise RuntimeError("二维码 2FA 成功，但未能获取用户 ID")
                await self._adopt_session_as_main(self._qr_password_session, user_id)
                await self._close_qr_password_session()
            else:
                await self._client.check_password(password)
            me = await self._mark_session_authorized()
            self._qr_login_tokens.clear()
            logger.info("[TG][QR] verify_2fa_password success")
            return {"status": "authorized", "user": me}
        except Exception as e:
            err = str(e).lower()
            logger.warning("[TG][QR] verify_2fa_password failed: %s", e)
            if "auth_key_unregistered" in err:
                await self._close_qr_password_session()
                raise RuntimeError("二维码登录会话已失效，请重新扫码")
            if "password" in err or "hash" in err:
                raise RuntimeError("两步验证密码错误")
            raise

    def _encode_qr_login_url(self, token_bytes: bytes) -> str:
        token_b64 = base64.urlsafe_b64encode(token_bytes).decode("ascii")
        return f"tg://login?token={token_b64}"

    async def _process_qr_login_result(self, result) -> Dict[str, Any]:
        """处理 export/import 返回类型，遵循 Telegram 官方 QR 登录流程"""
        if isinstance(result, raw.types.auth.LoginTokenSuccess):
            logger.info("[TG][QR] result=LoginTokenSuccess")
            me = await self._mark_session_authorized()
            return {"status": "authorized", "user": me}

        if isinstance(result, raw.types.auth.LoginToken):
            logger.info("[TG][QR] result=LoginToken (pending)")
            return {"status": "pending", "token": result.token}

        if isinstance(result, raw.types.auth.LoginTokenMigrateTo):
            logger.info("[TG][QR] result=LoginTokenMigrateTo dc_id=%s", result.dc_id)
            try:
                migrated = await self._import_qr_token_on_dc(result.token, result.dc_id)
            except SessionPasswordNeeded:
                logger.info("[TG][QR] migrate import requires 2FA password")
                return {"status": "password_required"}
            except Exception as e:
                err = str(e).upper()
                if "AUTH_TOKEN_EXPIRED" in err or "AUTH_TOKEN_INVALID" in err:
                    logger.info("[TG][QR] migrate import token expired/invalid, refresh required")
                    return {"status": "pending"}
                raise
            return await self._process_qr_login_result(migrated)

        raise RuntimeError("无法处理二维码登录响应")

    async def _export_qr_token(self) -> Dict[str, Any]:
        """按官方流程导出二维码 token；可能直接返回 authorized/password_required"""
        if not self._client:
            raise RuntimeError("客户端未初始化")

        result = await self._client.invoke(
            raw.functions.auth.ExportLoginToken(
                api_id=int(self._api_id),
                api_hash=str(self._api_hash),
                except_ids=[]
            )
        )
        return await self._process_qr_login_result(result)

    async def _import_qr_token_on_dc(self, token: bytes, dc_id: Optional[int] = None):
        """在指定 DC 导入二维码 token；处理 LoginTokenMigrateTo 时必须按 dc_id 执行。"""
        if not self._client:
            raise RuntimeError("客户端未初始化")

        if not dc_id or dc_id == await self._client.storage.dc_id():
            return await self._client.invoke(
                raw.functions.auth.ImportLoginToken(token=token)
            )

        session = Session(
            self._client,
            dc_id,
            await Auth(
                self._client,
                dc_id,
                await self._client.storage.test_mode()
            ).create(),
            await self._client.storage.test_mode(),
            is_media=False
        )
        keep_session = False
        try:
            await session.start()
            result = await session.invoke(
                raw.functions.auth.ImportLoginToken(token=token)
            )
            if isinstance(result, raw.types.auth.LoginTokenSuccess):
                # 无 2FA 的扫码成功，直接让该 session 接管主会话，避免 USER_MIGRATE。
                await self._adopt_session_as_main(session)
            return result
        except SessionPasswordNeeded:
            # 保留会话给 verify_2fa_password 使用，不能在这里关闭。
            await self._close_qr_password_session()
            self._qr_password_session = session
            self._qr_password_dc_id = dc_id
            keep_session = True
            raise
        finally:
            if not keep_session:
                await session.stop()

    async def _prepare_qr_password_session(self) -> Dict[str, Any]:
        """在提交 2FA 前按需导入当前二维码 token，建立可校验密码的会话。"""
        if self._qr_password_session:
            return {"status": "password_required"}
        if not self._qr_login_tokens:
            raise RuntimeError("二维码会话不存在，请重新扫码")

        token_states = sorted(
            self._qr_login_tokens.values(),
            key=lambda x: x.get("created_at", 0),
            reverse=True
        )
        last_err: Optional[Exception] = None
        for state in token_states:
            try:
                imported = await self._import_qr_token_on_dc(state["token"])
                result = await self._process_qr_login_result(imported)
                if result.get("status") == "authorized":
                    return result
            except SessionPasswordNeeded:
                return {"status": "password_required"}
            except Exception as e:
                last_err = e
                err = str(e).upper()
                if "AUTH_TOKEN_EXPIRED" in err or "AUTH_TOKEN_INVALID" in err:
                    continue
                raise

        if last_err:
            raise RuntimeError("二维码已失效，请重新生成并扫码")
        raise RuntimeError("二维码会话不存在，请重新扫码")

    async def start_qr_login(self) -> Dict[str, Any]:
        """启动二维码登录，返回扫码链接和 token_id"""
        await self._ensure_connected()
        await self._ensure_raw_update_handler()
        await self._ensure_nearest_dc_for_qr()
        await self._close_qr_password_session()
        if not self._client:
            raise RuntimeError("客户端未初始化")
        if not self._api_id or not self._api_hash:
            raise RuntimeError("请先配置 API ID 和 API Hash")

        exported: Dict[str, Any] = {}
        last_error: Optional[Exception] = None
        for _ in range(3):
            try:
                exported = await self._export_qr_token()
                break
            except Exception as e:
                last_error = e
                err = str(e).upper()
                if "AUTH_TOKEN_EXPIRED" in err or "AUTH_TOKEN_INVALID" in err:
                    logger.info("[TG][QR] start got expired token, retrying export")
                    await asyncio.sleep(0.3)
                    continue
                raise
        if not exported:
            if last_error:
                raise last_error
            raise RuntimeError("二维码初始化失败，请重试")
        if exported.get("status") == "authorized":
            return exported
        if exported.get("status") == "password_required":
            return {"status": "password_required"}

        token_bytes = exported["token"]

        token_id = secrets.token_urlsafe(16)
        self._qr_login_tokens[token_id] = {
            "token": token_bytes,
            "created_at": int(time.time()),
            "status": "pending",
            "next_check_at": 0
        }
        return {
            "status": "pending",
            "token_id": token_id,
            "login_url": self._encode_qr_login_url(token_bytes),
            "expires_in": 30
        }

    async def check_qr_login(self, token_id: str) -> Dict[str, Any]:
        """轮询二维码登录状态"""
        await self._ensure_connected()
        token_state = self._qr_login_tokens.get(token_id)
        if not token_state:
            return {"status": "expired", "message": "二维码已过期，请刷新"}

        if self._is_authorized:
            self._qr_login_tokens.pop(token_id, None)
            me = await self.get_me()
            return {"status": "authorized", "user": me}

        # 若扫码端已 accept，本端会收到 UpdateLoginToken；然后再次 export 才会得到 Success/MigrateTo。
        if self._qr_login_event.is_set():
            self._qr_login_event.clear()
            try:
                exported = await self._export_qr_token()
                if exported.get("status") == "authorized":
                    self._qr_login_tokens.pop(token_id, None)
                    return exported
                if exported.get("status") == "password_required":
                    token_state["status"] = "password_required"
                    return {"status": "password_required"}
                if exported.get("status") == "pending" and exported.get("token"):
                    new_token = exported["token"]
                    old_url = self._encode_qr_login_url(token_state["token"])
                    new_url = self._encode_qr_login_url(new_token)
                    token_state["token"] = new_token
                    token_state["created_at"] = int(time.time())
                    return {
                        "status": "pending",
                        "token_id": token_id,
                        "login_url": new_url,
                        "refresh": new_url != old_url
                    }
            except SessionPasswordNeeded:
                token_state["status"] = "password_required"
                return {"status": "password_required"}
            except Exception as e:
                logger.warning("[TG][QR] confirm after UpdateLoginToken failed: %s", e)

        # 一旦已准备好 2FA 会话，前端可直接输入密码，不再继续触碰二维码 token。
        if self._qr_password_session:
            token_state["status"] = "password_required"
            return {"status": "password_required"}

        if token_state.get("status") == "password_required":
            return {"status": "password_required"}

        if int(time.time()) - token_state.get("created_at", 0) > 120:
            self._qr_login_tokens.pop(token_id, None)
            return {"status": "expired", "message": "二维码已过期，请刷新"}

        now = int(time.time())
        if now < int(token_state.get("next_check_at", 0)):
            return {"status": "pending", "retry_after": int(token_state["next_check_at"] - now)}

        # 被动轮询：不调用 Telegram 的 import/export，避免二维码在扫码前被轮询失效。
        token_state["next_check_at"] = now + 5
        return {"status": "pending"}
    
    async def start(self) -> bool:
        """启动客户端（如果已有会话则直接登录）"""
        if not self._client:
            return False
        try:
            await self._ensure_connected()
            # 尝试获取当前用户，如果成功说明已登录
            me = await self._client.get_me()
            if me:
                self._is_authorized = True
                print(f"[TG] 已登录: {me.first_name} (@{me.username})")
                return True
        except Unauthorized:
            print("[TG] 会话已过期或未授权")
        except Exception as e:
            print(f"[TG] 启动失败: {e}")
        return False
    
    async def stop(self):
        """停止客户端"""
        async with self._lock:
            await self._close_qr_password_session()
            if self._client:
                try:
                    if self._client.is_connected:
                        await self._client.disconnect()
                    print("[TG] 已断开连接")
                except:
                    pass
                self._is_authorized = False
    
    async def get_me(self) -> dict:
        """获取当前用户信息 (带自动重连和缓存)"""
        if not self._client:
            return {}
            
        import time
        # 1. 检查缓存 (5分钟有效)
        async with self._cache_lock:
            if self._me_cache and (time.time() - self._me_cache_time < 300):
                return self._me_cache

        try:
            # 确保连接状态
            await self._ensure_connected()
            me = await self._client.get_me()
            if me:
                res = {
                    "id": me.id,
                    "first_name": me.first_name,
                    "last_name": me.last_name,
                    "username": me.username,
                    "phone": me.phone_number
                }
                # 2. 更新缓存
                async with self._cache_lock:
                    self._me_cache = res
                    self._me_cache_time = time.time()
                
                self._is_authorized = True
                return res
        except Unauthorized:
            self._is_authorized = False
            print("[TG] 会话已失效，需要重新登录")
            return {}
        except Exception as e:
            print(f"[TG] 获取用户信息失败: {e}")
            return {}

    def _convert_chat_type(self, chat: Chat) -> ChatType:
        """转换聊天类型"""
        if chat.type == PyChatType.PRIVATE:
            return ChatType.PRIVATE
        elif chat.type == PyChatType.BOT:
            return ChatType.BOT
        elif chat.type == PyChatType.GROUP:
            return ChatType.GROUP
        elif chat.type == PyChatType.SUPERGROUP:
            return ChatType.SUPERGROUP
        elif chat.type == PyChatType.CHANNEL:
            return ChatType.CHANNEL
        return ChatType.PRIVATE

    def get_media_type(self, msg: Message) -> Optional[MediaType]:
        """获取消息中的媒体类型"""
        if not msg:
            return None

        if msg.photo:
            return MediaType.PHOTO
        elif msg.video:
            return MediaType.VIDEO
        elif msg.audio:
            return MediaType.AUDIO
        elif msg.voice:
            return MediaType.VOICE
        elif msg.video_note:
            return MediaType.VIDEO_NOTE
        elif msg.document:
            return MediaType.DOCUMENT
        elif msg.sticker:
            return MediaType.STICKER
        elif msg.animation:
            return MediaType.ANIMATION

        return None

    async def get_dialogs(self, limit: int = 200) -> List[ChatInfo]:
        """获取对话列表，并顺手预热 peer 缓存。"""
        await self._ensure_connected()
        chats: List[ChatInfo] = []
        try:
            async for dialog in self._client.get_dialogs(limit=limit):
                try:
                    chats.append(self._convert_to_chat_info(dialog.chat))
                except Exception:
                    continue
            self._peers_warmed = True
            logger.info(f"[TG] get_dialogs 完成，获取 {len(chats)} 个对话并完成 peer 预热")
            return chats
        except Exception as e:
            logger.warning(f"[TG] 获取对话列表失败: {e}")
            raise RuntimeError(f"获取对话列表失败: {e}")

    async def get_chat_history(self, chat_id: Union[int, str], limit: int = 0, min_id: int = 0, max_id: int = 0, reverse: bool = False):
        """透传 Pyrogram get_chat_history，供扫描器使用（返回异步生成器）。"""
        await self._ensure_connected()
        async for msg in self._client.get_chat_history(
            chat_id,
            limit=limit,
            offset_id=0,
            offset_date=0,
            offset=0,
            max_id=max_id,
            min_id=min_id,
            reverse=reverse
        ):
            yield msg

    async def get_chat(self, chat_id: Union[int, str]) -> ChatInfo:
        """获取单个对话信息 (v2.4.2)"""
        await self._ensure_connected()
        
        # 定义尝试逻辑，便于复用
        async def try_get(cid):
            chat = await self._client.get_chat(cid)
            return self._convert_to_chat_info(chat)

        # 1. 尝试原始 ID
        try:
            return await try_get(chat_id)
        except Exception as e:
            error_str = str(e)
            
            # 针对 PEER_ID_INVALID/NAME_INVALID 进行预热和回退
            if "PEER_ID_INVALID" in error_str or "NAME_INVALID" in error_str:
                # A. 只有在没预热过的情况下才执行预热
                if not self._peers_warmed:
                    logger.warning(f"[TG] 遇到 Peer 报错，正在执行 Peer 预热 (全量拉取对话)...")
                    await self._warm_up_peer_cache()
                    # 预热后再次尝试原始 ID
                    try:
                        return await try_get(chat_id)
                    except:
                        pass

                # B. 智能回退: 尝试常见的 ID 变体
                str_id = str(abs(chat_id)) if isinstance(chat_id, int) else ""
                if str_id.startswith("100") and len(str_id) > 10:
                    base_id = int(str_id[3:])
                else:
                    base_id = int(str_id) if str_id.isdigit() else None

                if base_id:
                    if len(str(base_id)) >= 9:
                        try:
                            tid = int(f"-100{base_id}")
                            if tid != chat_id:
                                logger.info(f"[TG] 尝试超级群组回退 ID: {tid}")
                                return await try_get(tid)
                        except:
                            pass
                    try:
                        if base_id != chat_id:
                            logger.info(f"[TG] 尝试基础 ID 回退: {base_id}")
                            return await try_get(base_id)
                    except:
                        pass
                    try:
                        tid = -base_id
                        if tid != chat_id:
                            logger.info(f"[TG] 尝试负数 ID 回退: {tid}")
                            return await try_get(tid)
                    except:
                        pass
            raise RuntimeError(f"获取对话失败: {e}")

    def _convert_to_chat_info(self, chat: Chat) -> ChatInfo:
        title = chat.title or getattr(chat, 'first_name', None) or getattr(chat, 'username', None) or str(chat.id)
        return ChatInfo(
            id=chat.id,
            title=title,
            type=self._convert_chat_type(chat),
            username=getattr(chat, 'username', None),
            members_count=getattr(chat, 'members_count', None)
        )

    async def _warm_up_peer_cache(self):
        try:
            logger.info("[TG] 开始预热 Peer 缓存...")
            async for _ in self._client.get_dialogs(limit=200):
                pass
            self._peers_warmed = True
            logger.info("[TG] Peer 缓存预热完成")
        except Exception as e:
            logger.warning(f"[TG] Peer 缓存预热失败: {e}")

telegram_client = TelegramClient()
