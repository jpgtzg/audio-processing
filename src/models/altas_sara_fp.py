"""
ORM mapping for dbo.ALTAS_SARA_FP, SARA's own new-commercial alta queue and Tool 1's
real entry point. Column set and the (ID_TESTIGO, INICIO) composite primary key were
confirmed live against INFORMATION_SCHEMA.COLUMNS / sys.indexes on OrbitMedia_Test.
"""

from datetime import datetime

from sqlalchemy import CHAR, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class AltasSaraFP(Base):
    __tablename__ = "ALTAS_SARA_FP"

    id_testigo: Mapped[int] = mapped_column("ID_TESTIGO", primary_key=True)
    inicio: Mapped[int] = mapped_column("INICIO", primary_key=True)

    id_user: Mapped[int] = mapped_column("ID_USER")
    version: Mapped[str] = mapped_column("VERSION", VARCHAR(50))
    duracion: Mapped[int] = mapped_column("DURACION")
    estatus: Mapped[str] = mapped_column("ESTATUS", CHAR(1))
    id_altas_sara_fp: Mapped[int] = mapped_column("ID_ALTAS_SARA_FP")

    id_tipo_alta: Mapped[int | None] = mapped_column("ID_TIPO_ALTA")
    id_estatus_alta: Mapped[int | None] = mapped_column("ID_ESTATUS_ALTA")
    detalle: Mapped[str | None] = mapped_column("DETALLE", VARCHAR(500))
    offset_ini: Mapped[int | None] = mapped_column("OFFSET_INI")
    offset_fin: Mapped[int | None] = mapped_column("OFFSET_FIN")
    id_altas_sara_fp_padre: Mapped[int | None] = mapped_column("ID_ALTAS_SARA_FP_PADRE")
    id_segmento: Mapped[int | None] = mapped_column("ID_SEGMENTO")
    fecha_estatus: Mapped[datetime | None] = mapped_column("FECHA_ESTATUS")
    fecha_alta: Mapped[datetime | None] = mapped_column("FECHA_ALTA")
    id_fp_img: Mapped[int | None] = mapped_column("ID_FP_IMG")
    es_fp_img_sec: Mapped[int | None] = mapped_column("ES_FP_IMG_SEC")
    borrar_img_alt: Mapped[int | None] = mapped_column("BORRAR_IMG_ALT")
    id_user_descarte: Mapped[int | None] = mapped_column("ID_USER_DESCARTE")
    id_alta_auto_programacion: Mapped[int | None] = mapped_column("ID_ALTA_AUTO_PROGRAMACION")

    def __repr__(self) -> str:
        return (
            f"AltasSaraFP(id_altas_sara_fp={self.id_altas_sara_fp}, "
            f"id_testigo={self.id_testigo}, inicio={self.inicio}, "
            f"id_estatus_alta={self.id_estatus_alta})"
        )

    def compute_clip_times(self, fecha_inicio: datetime, range_start: datetime) -> tuple[float, float]:
        """
        Computes the start and end times of the clip within a combined-track timeline.

        Args:
            fecha_inicio: capture start of this alta's parent TESTIGO_SARA row.
            range_start: capture start of the first testigo in the combined track.

        Returns:
            tuple[float, float]: clip start and end, in seconds from range_start.
        """
        testigo_offset = (fecha_inicio - range_start).total_seconds()
        offset_ini = self.offset_ini or 0
        offset_fin = self.offset_fin or 0
        clip_start = testigo_offset + (self.inicio - offset_ini)
        clip_end = clip_start + self.duracion + offset_ini + offset_fin
        return clip_start, clip_end
