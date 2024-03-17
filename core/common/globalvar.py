from asyncio import Queue

from core.common.config_loader import ConfigLoader

new_res_q = Queue()
downloading_res_q = Queue()
success_res_q = Queue()
rename_q = Queue()
config_loader = ConfigLoader("config.yaml")
