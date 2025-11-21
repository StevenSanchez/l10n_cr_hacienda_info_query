# -*- coding: utf-8 -*-

import json
import logging
import requests

from odoo import models, api, fields, _

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # NUEVO CAMPO → Código actividad económica desde Hacienda
    hacienda_activity_code = fields.Char(
        string='Actividad económica (código Hacienda)',
        help='Código de actividad económica devuelto por el API de Hacienda.'
    )

    @api.onchange('vat')
    def onchange_vat(self):
        if self.vat:
            self.definir_informacion(self.vat)

    def definir_informacion(self, cedula):
        """Obtiene información tributaria desde el API de Hacienda CR usando la cédula."""

        # ---------------------------------------------------------------------
        # 1) Configuración desde la compañía
        # ---------------------------------------------------------------------
        company_id = self.env.company
        get_yo_contribuyo_information = company_id.get_yo_contribuyo_information
        get_tributary_information = company_id.get_tributary_information

        url_base = company_id.url_base
        url_base_yo_contribuyo = company_id.url_base_yo_contribuyo
        usuario_yo_contribuyo = company_id.usuario_yo_contribuyo
        token_yo_contribuyo = company_id.token_yo_contribuyo

        # ---------------------------------------------------------------------
        # 2) Si Yo Contribuyo estuviera activado (vos lo tenés desactivado)
        # ---------------------------------------------------------------------
        if (
            get_yo_contribuyo_information
            and url_base_yo_contribuyo
            and usuario_yo_contribuyo
            and token_yo_contribuyo
        ):
            try:
                end_point = url_base_yo_contribuyo + 'identificacion=' + cedula
                headers = {
                    "access-user": usuario_yo_contribuyo,
                    "access-token": token_yo_contribuyo,
                }
                respuesta = requests.get(end_point, headers=headers, timeout=10)

                company_id.ultima_respuesta_yo_contribuyo = (
                    f"{respuesta.status_code} - {respuesta.text}"
                )

                if respuesta.status_code in (200, 202):
                    data = json.loads(respuesta.text)
                    correos = data.get('Resultado', {}).get('Correos', [])
                    if correos:
                        # tomar todos los correos concatenados
                        self.email = ", ".join([c.get("Correo", "") for c in correos])

            except Exception as e:
                _logger.error("Error en consulta Yo Contribuyo: %s", e)

        # ---------------------------------------------------------------------
        # 3) Consulta de información tributaria HACIENDA (esta sí la usás)
        # ---------------------------------------------------------------------
        if url_base and get_tributary_information:
            try:
                end_point = url_base + "identificacion=" + cedula
                headers = {"content-type": "application/json"}
                respuesta = requests.get(end_point, headers=headers, timeout=10)

                company_id.ultima_respuesta = (
                    f"{respuesta.status_code} - {respuesta.text}"
                )

                if respuesta.status_code in (200, 202) and respuesta.content:
                    contenido = json.loads(respuesta.content.decode("utf-8"))

                    # -----------------------------------------------------------------
                    # NOMBRE DEL CLIENTE (ya lo hacía el módulo original)
                    # -----------------------------------------------------------------
                    if contenido.get("nombre"):
                        self.name = contenido.get("nombre")

                    # -----------------------------------------------------------------
                    # NUEVO → Guardar la Actividad Económica de Hacienda
                    # -----------------------------------------------------------------
                    actividades = contenido.get("actividades") or []
                    self.hacienda_activity_code = False  # limpiar valor anterior

                    if actividades:
                        # buscar actividad estado 'A'
                        actividad_activa = next(
                            (a for a in actividades if a.get("estado") == "A"), None
                        )

                        # si no hay activa, usar la primera
                        if not actividad_activa:
                            actividad_activa = actividades[0]

                        # Capturar el código (normalmente es "codigo")
                        self.hacienda_activity_code = str(
                            actividad_activa.get("codigo") or ""
                        )

            except Exception as e:
                _logger.error("Error consultando Hacienda: %s", e)
                company_id.ultima_respuesta = f"Error: {e}"
