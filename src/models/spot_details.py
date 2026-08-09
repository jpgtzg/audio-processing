"""
Obtained from fetching ALTAS_SARA_FP and TESTIGO_SARA records from the database, this data structure represents the details of a specific spot
"""

from datetime import datetime


class SpotDetails:
    def __init__(
        self,
        id_altas_sara_fp: int,
        id_testigo: int,
        version: str,
        inicio: float,
        duracion: float,
        offset_ini: float,
        offset_fin: float,
        id_estatus_alta: int,
        fecha_inicio: datetime,
    ):
        self.id_altas_sara_fp = id_altas_sara_fp
        self.id_testigo = id_testigo
        self.version = version
        self.inicio = inicio
        self.duracion = duracion
        self.offset_ini = offset_ini
        self.offset_fin = offset_fin
        self.id_estatus_alta = id_estatus_alta
        self.fecha_inicio = fecha_inicio

    def __repr__(self):
        return f"SpotDetails(id_altas_sara_fp={self.id_altas_sara_fp}, id_testigo={self.id_testigo}, version='{self.version}', inicio={self.inicio}, duracion={self.duracion}, offset_ini={self.offset_ini}, offset_fin={self.offset_fin}, id_estatus_alta={self.id_estatus_alta}, fecha_inicio='{self.fecha_inicio}')"

    def compute_clip_times(self, range_start: datetime) -> tuple[float, float]:
        """
        Computes the start and end times of the clip based on the spot details and the provided range start time.

        Args:
            range_start (float): The start time of the range in seconds.

        Returns:
            tuple[float, float]: A tuple containing the start and end times of the clip in seconds.
        """

        testigo_offset = (self.fecha_inicio - range_start).total_seconds()
        clip_start = testigo_offset + (self.inicio - self.offset_ini)
        clip_end = clip_start + self.duracion + self.offset_ini + self.offset_fin
        return clip_start, clip_end
