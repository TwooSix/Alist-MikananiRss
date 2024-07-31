import argparse
import asyncio
import sys

from alist_mikananirss.common import initializer


async def main():
    parser = argparse.ArgumentParser(description="Alist Mikanani RSS")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the configuration file",
    )

    args = parser.parse_args()

    initializer.read_config(args.config)
    initializer.setup_logger()
    initializer.setup_proxy()
    alist_client = await initializer.init_alist()
    initializer.init_download_manager(alist_client)
    initializer.init_renamer(alist_client)
    resource_filters = initializer.init_resource_filter()
    rss_monitor = initializer.init_rss_monitor(resource_filters)
    initializer.init_notification_sender()

    task = asyncio.create_task(rss_monitor.run())
    await task


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
