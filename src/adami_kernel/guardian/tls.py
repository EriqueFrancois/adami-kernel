import hashlib
import hmac
import json
import logging
import os
import secrets

from adami_kernel.config import settings

logger = logging.getLogger("GuardianTLS")


class LocalSecretVault:
    def __init__(self, key_file: str | None = None):
        self.key_file = key_file if key_file is not None else settings.path_keystore_json
        self.keys = {}
        self._load_or_generate()

    def _load_or_generate(self):
        """持久化 KeyStore 逻辑"""
        if os.path.exists(self.key_file):
            try:
                with open(self.key_file, "r") as f:
                    self.keys = json.load(f)
                logger.info("[TLS] Loaded persistent KeyStore.")
            except Exception as e:
                logger.error(f"[TLS] KeyStore corrupted: {e}. Regenerating...")
                self._generate_new_vault()
        else:
            self._generate_new_vault()

    def _generate_new_vault(self):
        """生成并安全保存新的主密钥"""
        self.keys = {"master_node": secrets.token_hex(32), "version": "1.0"}
        with open(self.key_file, "w") as f:
            # 严格限制文件权限 (如果在类Unix系统下)
            os.chmod(self.key_file, 0o600) if os.name == "posix" else None
            json.dump(self.keys, f)
        logger.info("[TLS] Generated new persistent KeyStore.")

    def generate_token(self, payload: str) -> str:
        """使用持久化主密钥生成 HMAC 签名"""
        secret = self.keys.get("master_node", "").encode()
        return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()

    def verify_token(self, payload: str, token: str) -> bool:
        expected = self.generate_token(payload)
        return hmac.compare_digest(expected, token)
