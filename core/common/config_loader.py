import yaml


class ConfigLoader:
    def __init__(self, config_path):
        self.config_path = config_path
        self.config = self.load_config()

    def load_config(self):
        with open(self.config_path, "r", encoding="utf-8") as file:
            return yaml.safe_load(file)

    def get(self, path, default=None):
        keys = path.split(".")
        value = self.config
        for key in keys:
            if value.get(key) is None:
                if default is not None:
                    return default
                else:
                    raise ValueError(
                        f"{path} is not found in config file {self.config_path}"
                    )
            value = value[key]
        return value
