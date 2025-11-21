# -*- coding: utf-8 -*-

import json
import logging
import requests

from odoo import models, api, fields, _
from datetime import datetime

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # -------------------------------
    # CAMPOS HACIENDA
    # -------------------------------
    hacienda_activity_code = fields.Char(
        string='Actividad económica (código Hacienda)',
        help='Código de actividad económica devuelto por Hacienda.'
    )

    hacienda_inscribed = fields.Boolean(
        string='Inscrito en Hacienda',
        help='Indica si el contribuyente está inscrito según Hacienda.'
    )

    hacienda_status = fields.Char(
        string='Estado en Hacienda',
        help='Estado textual devuelto por Hacienda (Inscrito, Inscrito de Oficio, Inactivo, etc.).'
    )

    # -------------------------------
    # LIMPIAR CÉDULA
    # -------------------------------
    def limpiar_cedula(self, cedula):
        if cedula:
            cedula = cedula.replace("-", "")
        return cedula

    # -------------------------------
    # ONCHANGE VAT
    # -------------------------------
    @api.onchange('vat')
    def onchange_vat(self):
        if self.vat:
            self.definir_informacion(self.vat)

    # -------------------------------
    # CONSULTA HACIENDA
    # -------------------------------
    def definir_informacion(self, cedula):

        cedula = self.limpiar_cedula(cedula)

        company_id = self.env.company

        url_base = company_id.url_base
        url_base_yo = company_id.url_base_yo_contribuyo
        usuario_yo = company_id.usuario_yo_contribuyo
        token_yo = company_id.token_yo_contribuyo

        get_yo = company_id.get_yo_contribuyo_information
        get_tributaria = company_id.get_tributary_information

        # ------------------------------------------------------------
        # YO CONTRIBUYO (si está activado)
        # ------------------------------------------------------------
        if get_yo and url_base_yo and usuario_yo and token_yo:
            try:
                endpoint = url_base_yo + "identificacion=" + cedula
                headers = {
                    "access-user": usuario_yo,
                    "access-token": token_yo,
                }

                r = requests.get(endpoint, headers=headers, timeout=10)
                company_id.ultima_respuesta_yo_contribuyo = f"{r.status_code} - {r.text}"

                if r.status_code in (200, 202):
                    data = json.loads(r.text)
                    correos = data.get("Resultado", {}).get("Correos", [])
                    if correos:
                        self.email = ", ".join(c.get("Correo", "") for c in correos)

            except Exception as e:
                _logger.error("Error Yo Contribuyo: %s", e)

        # ------------------------------------------------------------
        # CONSULTA A HACIENDA NORMAL
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
                    # NOMBRE
                    # --------------------------
                    if contenido.get("nombre"):
                        self.name = contenido.get("nombre")

                    # --------------------------
                    # TIPO DE IDENTIFICACIÓN
                    # --------------------------
                    if "identification_id" in self._fields:
                        tipo = contenido.get("tipoIdentificacion")
                        if tipo:
                            ident_type = self.env["identification.type"].search(
                                [("code", "=", tipo)],
                                limit=1
                            )
                            self.identification_id = ident_type.id

                    # --------------------------
                    # ESTADO / INSCRIPCIÓN EN HACIENDA
                    # --------------------------
                    situacion = contenido.get("situacion") or {}
                    estado = situacion.get("estado") or ""
                    self.hacienda_status = estado
                    # Puedes ajustar esta condición si Hacienda usa otros textos
                    self.hacienda_inscribed = estado in (
                        "Inscrito",
                        "Inscrito de Oficio",
                        "Activo",
                    )

                    # --------------------------
                    # ACTIVIDAD ECONÓMICA
                    # --------------------------
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

                    # --------------------------
                    # LÓGICA ORIGINAL activity_id
                    # --------------------------
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

