# -*- coding: utf-8 -*-

import json
import logging
import requests

from odoo import models, api, fields, _
from datetime import datetime

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # NUEVO CAMPO → Código actividad económica de Hacienda
    hacienda_activity_code = fields.Char(
        string='Actividad económica (código Hacienda)',
        help='Código de actividad económica devuelto por el API de Hacienda.'
    )

    # ------------------------------------------------------------
    # LIMPIAR CÉDULA (viene del módulo original)
    # ------------------------------------------------------------
    def limpiar_cedula(self, cedula):
        if cedula:
            cedula = cedula.replace("-", "")
        return cedula

    # ------------------------------------------------------------
    # EVENTO AL CAMBIAR VAT
    # ------------------------------------------------------------
    @api.onchange('vat')
    def onchange_vat(self):
        if self.vat:
            self.definir_informacion(self.vat)

    # ------------------------------------------------------------
    # CONSULTAR INFORMACIÓN TRIBUTARIA (HACIENDA)
    # ------------------------------------------------------------
    def definir_informacion(self, cedula):

        cedula = self.limpiar_cedula(cedula)

        company_id = self.env.company

        url_base = company_id.url_base
        url_base_yo_contribuyo = company_id.url_base_yo_contribuyo
        get_yo_contribuyo_information = company_id.get_yo_contribuyo_information
        get_tributary_information = company_id.get_tributary_information
        usuario_yo_contribuyo = company_id.usuario_yo_contribuyo
        token_yo_contribuyo = company_id.token_yo_contribuyo

        # ------------------------------------------------------------
        # YO CONTRIBUYO (si está activado)
        # ------------------------------------------------------------
        if (
            get_yo_contribuyo_information
            and url_base_yo_contribuyo
            and usuario_yo_contribuyo
            and token_yo_contribuyo
        ):
            try:
                end_point = url_base_yo_contribuyo + 'identificacion=' + cedula
                headers = {
                    'access-user': usuario_yo_contribuyo,
                    'access-token': token_yo_contribuyo
                }
                peticion = requests.get(end_point, headers=headers, timeout=10)

                company_id.ultima_respuesta_yo_contribuyo = (
                    f"{peticion.status_code} - {peticion.text}"
                )

                if peticion.status_code in (200, 202):
                    contenido = json.loads(peticion.text)
                    correos = contenido.get('Resultado', {}).get('Correos', [])
                    if correos:
                        self.email = ", ".join(c.get("Correo", "") for c in correos)

            except Exception as e:
                _logger.error("Error Yo Contribuyo: %s", e)

        # ------------------------------------------------------------
        # CONSULTA HACIENDA NORMAL
        # ------------------------------------------------------------
        if url_base and get_tributary_information:
            try:
                end_point = url_base + 'identificacion=' + cedula
                headers = {"content-type": "application/json"}
                peticion = requests.get(end_point, headers=headers, timeout=10)

                company_id.ultima_respuesta = (
                    f"{peticion.status_code} - {peticion.text}"
                )

                if peticion.status_code in (200, 202) and peticion.content:
                    contenido = json.loads(peticion.content.decode('utf-8'))

                    # --------------------------
                    # GUARDAR NOMBRE DEL CLIENTE
                    # --------------------------
                    if contenido.get('nombre'):
                        self.name = contenido.get('nombre')

                    # --------------------------
                    # TIPO ID (si existe en Odoo)
                    # --------------------------
                    if 'identification_id' in self._fields:
                        clasificacion = contenido.get('tipoIdentificacion')
                        if clasificacion:
                            ident_type = self.env['identification.type'].search(
                                [('code', '=', clasificacion)], limit=1
                            )
                            self.identification_id = ident_type.id

                    # ------------------------------------------------
                    # NUEVO: GUARDAR CÓDIGO DE ACTIVIDAD ECONÓMICA
                    # ------------------------------------------------
                    actividades = contenido.get('actividades') or []
                    self.hacienda_activity_code = False  # limpiar valor previo

                    if actividades:
                        actividad_activa = next(
                            (a for a in actividades if a.get('estado') == 'A'),
                            None
                        )
                        if not actividad_activa:
                            actividad_activa = actividades[0]

                        self.hacienda_activity_code = str(
                            actividad_activa.get('codigo') or ''
                        )

                    # ------------------------------------------------
                    # LÓGICA ORIGINAL PARA economic.activity
                    # (la dejamos intacta aunque no la uses)
                    # ------------------------------------------------
                    if contenido.get('actividades') and 'activity_id' in self._fields:
                        for act in contenido.get('actividades'):
                            if act.get('estado') == 'A':
                                actividad = self.env['economic.activity'].search(
                                    [('code', '=', str(act.get('codigo')))],
                                    limit=1
                                )
                                if actividad:
                                    self.activity_id = actividad.id
                                    if hasattr(self, 'action_get_economic_activities'):
                                        self.action_get_economic_activities()

            except Exception as e:
                _logger.error("Error consultando Hacienda: %s", e)
                company_id.ultima_respuesta = f"Error: {e}"
