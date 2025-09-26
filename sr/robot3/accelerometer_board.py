"""The servo board module provides an interface to the servo board firmware over serial."""
from __future__ import annotations

import atexit
import logging
from types import MappingProxyType
from typing import Optional
from math import pi

from serial.tools.list_ports import comports

from .exceptions import IncorrectBoardError
from .logging import log_to_debug
from .serial_wrapper import SerialWrapper
from .utils import (
    IN_SIMULATOR, Board, BoardIdentity, float_bounds_check,
    get_simulator_boards, get_USB_identity, map_to_float, map_to_int,
)

DUTY_MIN = 500
DUTY_MAX = 4000
START_DUTY_MIN = 1000
START_DUTY_MAX = 2000
NUM_SERVOS = 12

logger = logging.getLogger(__name__)
BAUDRATE = 115200  # Since the servo board is a USB device, this is ignored


class AccelerometerBoard(Board):
    """
    A class representing the servo board interface.

    This class is intended to be used to communicate with the servo board over serial
    using the text-based protocol added in version 4.3 of the servo board firmware.

    :param serial_port: The serial port to connect to.
    :param initial_identity: The identity of the board, as reported by the USB descriptor.
    """
    __slots__ = ('_serial', '_identity')

    @staticmethod
    def get_board_type() -> str:
        """
        Return the type of the board.

        :return: The literal string 'Accelerometer'.
        """
        return 'Accelerometer'

    def __init__(
        self,
        serial_port: str,
        initial_identity: Optional[BoardIdentity] = None,
    ) -> None:
        if initial_identity is None:
            initial_identity = BoardIdentity()
        self._serial = SerialWrapper(serial_port, BAUDRATE, identity=initial_identity)

        self._identity = self.identify()
        if self._identity.board_type != self.get_board_type():
            raise IncorrectBoardError(self._identity.board_type, self.get_board_type())
        self._serial.set_identity(self._identity)

        atexit.register(self._cleanup)
    
    @classmethod
    def _get_valid_board(
        cls,
        serial_port: str,
        initial_identity: Optional[BoardIdentity] = None,
    ) -> Optional[AccelerometerBoard]:
        """
        Attempt to connect to an accelerometer board and returning None if it fails identification.

        :param serial_port: The serial port to connect to.
        :param initial_identity: The identity of the board, as reported by the USB descriptor.

        :return: A AccelerometerBoard object, or None if the board could not be identified.
        """
        try:
            board = cls(serial_port, initial_identity)
        except IncorrectBoardError as err:
            logger.warning(
                f"Board returned type {err.returned_type!r}, "
                f"expected {err.expected_type!r}. Ignoring this device")
            return None
        except Exception as err:
            if initial_identity is not None:
                if initial_identity.board_type == 'manual':
                    logger.warning(
                        f"Manually specified accelerometer board at port {serial_port!r}, "
                        "could not be identified. Ignoring this device")
                elif initial_identity.manufacturer == 'sbot_simulator':
                    logger.warning(
                        f"Simulator specified accelerometer board at port {serial_port!r}, "
                        "could not be identified. Ignoring this device")
                return None

            logger.warning(
                f"Found accelerometer board-like serial port at {serial_port!r}, "
                "but it could not be identified. Ignoring this device")
            return None
        return board
    
    @classmethod
    def _get_simulator_boards(cls) -> MappingProxyType[str, AccelerometerBoard]:
        """
        Get the simulator boards.

        :return: A mapping of board serial numbers to board.
        """
        boards = {}
        # The filter here is the name of the emulated board in the simulator
        for board_info in get_simulator_boards('AccelerometerBoard'):

            # Create board identity from the info given
            initial_identity = BoardIdentity(
                manufacturer='sbot_simulator',
                board_type=board_info.type_str,
                asset_tag=board_info.serial_number,
            )
            if (board := cls._get_valid_board(board_info.url, initial_identity)) is None:
                continue

            boards[board._identity.asset_tag] = board
        return MappingProxyType(boards)
    
    @classmethod
    def _get_supported_boards(
        cls, manual_boards: Optional[list[str]] = None,
    ) -> MappingProxyType[str, AccelerometerBoard]:
        """
        Find all connected accelerometer boards.

        Ports are filtered to the USB vendor and product ID: TODO: CHECK THIS

        :param manual_boards: A list of manually specified serial ports to also attempt
            to connect to, defaults to None
        :return: A mapping of serial numbers to accelerometer boards.
        """
        if IN_SIMULATOR:
            return cls._get_simulator_boards()

        return cls._get_simulator_boards()
    
    @log_to_debug
    def identify(self) -> BoardIdentity:
        """
        Get the identity of the board.

        :return: The identity of the board.
        """
        response = self._serial.query('*IDN?')
        return BoardIdentity(*response.split(':'))
    
    @property
    @log_to_debug
    def status(self) -> str:
        """
        Get the status of the board.

        :return: The status of the board.
        """
        return self._serial.query('*STATUS?')
    
    @log_to_debug
    def reset(self) -> str:
        """
        Reset the board.

        :return: The response from the board.
        """
        return self._serial.query('*RESET')
    
    @property
    @log_to_debug
    def acceleration(self) -> tuple[float, float, float]:
        """
        Read the acceleration from the board.

        :return: A tuple of the acceleration in the X, Y, and Z axes in m/s^2.
        """
        response = self._serial.query('ACC:READ?')
        return [float(x) for x in response.split(':')]

    def _cleanup(self) -> None:
        """
        Reset the board and disable all servos on exit.

        This is registered as an exit function.
        """
        try:
            self.reset()
        except Exception:
            logger.warning(f"Failed to cleanup servo board {self._identity.asset_tag}.")

    def __repr__(self) -> str:
        return f"<{self.__class__.__qualname__}: {self._serial}>"