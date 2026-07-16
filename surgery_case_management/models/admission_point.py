# -*- coding: utf-8 -*-
from odoo import models, fields

class AdmissionPoint(models.Model):
    _name = 'admission.point'
    _description = 'Admission Point'

    name = fields.Char(string="Name")
    admission_type = fields.Selection([('daycare', 'Day Care'),('overnight', 'Overnight Stay'),('private', 'Private Practice')])