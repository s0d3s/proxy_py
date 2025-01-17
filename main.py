#!/usr/bin/env python3
import os

import uvloop

uvloop.install()

from proxy_py import settings
from processor import Processor
from server.proxy_provider_server import ProxyProviderServer
from statistics import statistics
from checkers.base_checker import BaseChecker
from tools import test_collector

import materialized_view_updater
import asyncio
import logging
import argparse
import subprocess
import sys



test_collector_path = None
main_logger = None


def process_cmd_arguments():
    global test_collector_path

    def str_to_bool(value):
        if value.lower() in ("yes", "true", "t", "y", "1"):
            return True
        elif value.lower() in ("no", "false", "f", "n", "0"):
            return False
        else:
            raise argparse.ArgumentTypeError("Boolean value expected.")

    cmd_parser = argparse.ArgumentParser()
    cmd_parser.add_argument("--debug", type=str_to_bool, help="override settings' debug value")
    cmd_parser.add_argument(
        "--proxy-checking-timeout", type=float, help="override settings' proxy checking timeout"
    )
    cmd_parser.add_argument("--test-collector", help="test collector with a given path")

    args = cmd_parser.parse_args()

    if args.debug is not None:
        settings.DEBUG = args.debug

    if args.proxy_checking_timeout is not None:
        if args.proxy_checking_timeout < 0:
            raise ValueError("--proxy-checking-timeout should be positive")

        settings.PROXY_CHECKING_TIMEOUT = args.proxy_checking_timeout

    test_collector_path = args.test_collector


def prepare_loggers():
    global main_logger

    asyncio_logger = logging.getLogger("asyncio")
    asyncio_logger_file_handler = logging.FileHandler("logs/asyncio.log")
    asyncio_logger_file_handler.setLevel(logging.DEBUG)
    asyncio_logger_file_handler.setFormatter(
        logging.Formatter(
            "%(levelname)s ~ %(asctime)s ~ %(funcName)30s() - %(message)s"
        )
    )
    asyncio_logger.addHandler(asyncio_logger_file_handler)

    if settings.DEBUG:
        asyncio.get_event_loop().set_debug(True)

        asyncio_logger.setLevel(logging.DEBUG)

    main_logger = logging.getLogger("proxy_py/main")

    if settings.DEBUG:
        main_logger.setLevel(logging.DEBUG)
    else:
        main_logger.setLevel(logging.INFO)

    logger_file_handler = logging.FileHandler("logs/main.log")
    logger_file_handler.setLevel(logging.DEBUG)
    logger_file_handler.setFormatter(
        logging.Formatter(
            "%(levelname)s ~ %(asctime)s ~ %(funcName)30s() ~ %(message)s"
        )
    )

    main_logger.addHandler(logger_file_handler)


async def core():

    process_cmd_arguments()
    prepare_loggers()

    if test_collector_path is not None:
        return await test_collector.run(test_collector_path)

    proxy_processor = Processor.get_instance()

    try:
        code = await asyncio.gather(*[
            proxy_processor.worker(),
            statistics.worker(),
            materialized_view_updater.worker(),
        ])
        BaseChecker.clean()
        return code
    except KeyboardInterrupt:
        pass
    except BaseException as ex:
        main_logger.exception(ex)
        print("critical error happened, see logs/main.log")
        return 1

    return 0


def server():
    proxy_provider_server = ProxyProviderServer(
        settings.PROXY_PROVIDER_SERVER_ADDRESS['HOST'],
        settings.PROXY_PROVIDER_SERVER_ADDRESS['PORT'],
    )

    return proxy_provider_server.start(asyncio.get_event_loop())


def main():
    if len(sys.argv) < 2:
        # run default configuration
        # server
        p = subprocess.Popen(["python3", sys.argv[0], 'server'])

        # and core
        code = asyncio.get_event_loop().run_until_complete(core())
        p.wait()
        return code

    command = sys.argv[1].strip()
    sys.argv = sys.argv[1:]
    return {
        'core': lambda: asyncio.get_event_loop().run_until_complete(core()),
        'server': server,
    }[command]()


if __name__ == "__main__":
    exit(main())
