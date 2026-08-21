from typing import List, Any, Optional, Dict


class RasaIntent:
    def __init__(self, message: str, intent: Optional[int] = None, params: Optional[Dict[str, Any]] = None):
        self.message: str = message
        self.intent: Optional[int] = intent
        # 如果传入None，默认赋值为空字典
        self.params: Dict[str, Any] = params if params is not None else {}

    def __repr__(self):
        return f"RasaIntent(message={repr(self.message)}, intent={self.intent}, params={repr(self.params)})"