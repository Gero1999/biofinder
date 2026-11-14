"""Offline test guards and minimal case helpers."""

import unittest
from unittest.mock import patch
from runtime import scenario_investigation


class OfflineTest(unittest.TestCase):
    def setUp(self):
        for target in (
            "socket.socket.connect",
            "socket.socket.connect_ex",
            "socket.socket.sendto",
            "socket.getaddrinfo",
        ):
            guard = patch(
                target,
                side_effect=AssertionError("Network is forbidden in automated tests"),
            )
            guard.start()
            self.addCleanup(guard.stop)


def run_case(number, cache=None):
    agent, transport, fixture = scenario_investigation(number, cache)
    report = agent.run(fixture["query"], requirements=fixture["requirements"])
    return agent, transport, fixture, report
