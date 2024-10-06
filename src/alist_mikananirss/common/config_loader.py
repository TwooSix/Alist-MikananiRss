import yaml


class ConfigLoader:
    """A class for loading and accessing YAML configuration files.

    This class provides methods to load a YAML config file and retrieve values
    using dot notation paths.

    Attributes:
        config_path (str): The path to the YAML configuration file.
        config (dict): The loaded configuration data.

    Example:
        >>> config_loader = ConfigLoader('config.yaml')
        >>> database_url = config_loader.get('database.url')
        >>> port = config_loader.get('server.port', default=8080)
    """

    _MISSING = object()

    def __init__(self, config_path):
        """Initializes the ConfigLoader with the given config file path.

        Args:
            config_path (str): The path to the YAML configuration file.
        """
        self.config_path = config_path
        self.config = self.load_config()

    def load_config(self):
        """Loads the YAML configuration file.

        Returns:
            dict: The loaded configuration data.

        Raises:
            yaml.YAMLError: If there's an error parsing the YAML file.
        """
        with open(self.config_path, "r", encoding="utf-8") as file:
            return yaml.safe_load(file)

    def get(self, path, default=_MISSING):
        """Retrieves a value from the configuration using a dot notation path.

        Args:
            path (str): The dot notation path to the desired configuration value.
            default: The default value to return if the path is not found.
                     If not provided, a KeyError will be raised.

        Returns:
            The value at the specified path in the configuration.

        Raises:
            KeyError: If the path is not found and no default value is provided.
        """
        keys = path.split(".")
        value = self.config
        for key in keys:
            if value.get(key) is None:
                if default is not self._MISSING:
                    return default
                else:
                    raise KeyError(
                        f"{path} is not found in config file {self.config_path}"
                    )
            value = value[key]
        return value
