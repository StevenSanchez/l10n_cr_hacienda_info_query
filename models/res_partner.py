# -*- coding: utf-8 -*-

import json
import logging
import requests

from odoo import models, api, fields, _
from datetime import datetime

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # NUEVO CAMPO → código de actividad económica de Hacienda
    hacienda_activity_code = fields.Char(
        string='Actividad económica (código Hacienda)',
        help='Código de actividad económica devuelto por el API de Hacienda.'
    )

    # ------------------------------------------------------------
    # Limpieza de cédula (igual que el módulo original)
    # ------------------------------------------------------------
    def limpiar_cedula(self, cedula):
        if cedula:
            cedula = cedula.replace("-", "")
        return cedula

    # ------------------------------------------------------------
    # Evento al cambiar la cédula
    # ------------------------------------------------------------
    @api.onchange('vat')
    def onchange_vat(self):
        if self.vat:
            self.definir_informacion(self.vat)

    # ------------------------------------------------------------
    # Consulta al API de Hacienda
    # ------------------------------------------------------------
    def definir_informacion(self, cedula):

        cedula = self.limpiar_cedula(cedula)

        company_id = self.env.company

        url_base = company_id.url_base
        url_base_yo_contribuyo = company_id.url_base_yo_contribuyo
        usuario_yo_contribuyo = company_id.usuario_yo_contribuyo
        token_yo_contribuyo = company_id.token_yo_contribuyo

        get_yo_contribuyo = company_id.get_yo_contribuyo_information
        get_tributaria = company_id.get_tributary_information

        # ------------------------------------------------------------
        # 1) YO CONTRIBUYO (si está activado)
        # ------------------------------------------------------------
        if (
            get_yo_contribuyo
            and url_base_yo_contribuyo
            and usuario_yo_contribuyo
            and token_yo_contribuyo
        ):
            try:
                endpoint = url_base_yo_contribuyo + "identificacion=" + cedula
                headers = {
                    "access-user": usuario_yo_contribuyo,
                    "access-token": token_yo_contribuyo
                }
                r = requests.get(endpoint, headers=headers, timeout=10)

                company_id.ultima_respuesta_yo_contribuyo = f"{r.status_code} - {r.text}"

                if r.status_code in (200, 202):
                    data = json.loads(r.text)
                    correos = data.get("Resultado", {}).get("Correos", [])
                    if correos:
                        self.email = ", ".join([c.get("Correo", "") for c in correos])

            except Exception as e:
                _logger.error("Error Yo Contribuyo: %s", e)

        # ------------------------------------------------------------
        # 2) CONSULTA HACIENDA NORMAL
        # ------------------------------------------------------------
        if url_base and get_tributaria:
            try:
                endpoint = url_base + "identificacion=" + cedula
                headers = {"content-type": "application/json"}

                r = requests.get(endpoint, headers=headers, timeout=10)
                company_id.ultima_respuesta = f"{r.status_code} - {r.text}"

                if r.status_code in (200, 202) and r.content:
                    contenido = json.loads(r.content.decode("utf-8"))

                    # --------------------------
                    # Nombre del contribuyente
                    # --------------------------
                    if contenido.get("nombre"):
                        self.name = contenido.get("nombre")

                    # --------------------------
                    # Tipo de identificación
                    # --------------------------
                    if "identification_id" in self._fields:
                        tipo = contenido.get("tipoIdentificacion")
                        if tipo:
                            ident_type = self.env["identification.type"].search(
                                [("code", "=", tipo)],
                                limit=1
                            )
                            self.identification_id = ident_type.id

                    # ------------------------------------------------------------
                    # NUEVO: Guardar código actividad económica
                    # ------------------------------------------------------------
                    actividades = contenido.get("actividades") or []
                    self.hacienda_activity_code = False

                    if actividades:
                        actividad_activa = next(
                            (a for a in actividades if a.get("estado") == "A"),
                            None
                        )
                        if not actividad_activa:
                            actividad_activa = actividades[0]

                        self.hacienda_activity_code = str(
                            actividad_activa.get("codigo") or ""
                        )


                    # ------------------------------------------------------------
                    # Lógica original del módulo: asignar activity_id si existe
                    # ------------------------------------------------------------
                    if actividades and "activity_id" in self._fields:
                        for act in actividades:
                            if act.get("estado") == "A":
                                actividad = self.env["economic.activity"].search(
                                    [("code", "=", str(act.get("codigo")))],
                                    limit=1
                                )
                                if actividad:
                                    self.activity_id = actividad.id
                                    if hasattr(self, "action_get_economic_activities"):
                                        self.action_get_economic_activities()

            except Exception as e:
                _logger.error("Error consultando Hacienda: %s", e)
                company_id.ultima_respuesta = "Error: %s" % e
