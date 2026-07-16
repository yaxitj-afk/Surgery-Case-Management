# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    mediris_patient_id = fields.Char(
        string='Mediris Patient ID',
        help='Unique patient identifier assigned by Mediris system. '
             'Used as the primary key to match and update existing records during import.'
    )
    mediris_age = fields.Integer(
        string='Age',
        help='Patient age as exported from Mediris. '
             'This is a static value from the export file and is not auto-calculated from date of birth.'
    )
    mediris_spoken_language = fields.Char(
        string='Spoken Language',
        help='The language the patient speaks during consultations, '
             'as recorded in Mediris. May differ from the administrative language.'
    )
    mediris_general_practitioner = fields.Char(
        string='General Practitioner',
        help='Name or RIZIV/INAMI number of the general practitioner '
             'linked to this patient in Mediris.'
    )
    mediris_creation_date = fields.Date(
        string='Mediris Creation Date',
        help='The date this patient record was originally created in the Mediris system. '
             'Not the same as the Odoo record creation date.'
    )
    mediris_archived = fields.Boolean(
        string='Archived in Mediris',
        help='Indicates whether this patient has been archived/deactivated in Mediris. '
             'Archived patients are no longer active in the practice.'
    )
    mediris_mutual_fund_name = fields.Char(
        string='Mutual Fund Name',
        help='Full name of the Belgian mutual insurance fund (mutualiteit) '
             'the patient is affiliated with, e.g. CM, Solidaris, Mutualité Neutre.'
    )
    mediris_mutual_fund_code = fields.Char(
        string='Mutual Fund Code',
        help='Numeric code identifying the mutual fund. '
             'Used for billing and insurance claim processing in Belgium.'
    )
    mediris_insurance_category = fields.Char(
        string='Insurance Category (CT1/CT2)',
        help='Belgian health insurance category codes CT1 and CT2 '
             'that determine the patient reimbursement rate for medical procedures.'
    )
    mediris_insurability_status = fields.Char(
        string='Insurability Status',
        help='Current insurability status of the patient, e.g. "Verzekerd" (Insured) or '
             '"Verhoogde tegemoetkoming" (Increased reimbursement). Sourced from mutuality data.'
    )
    mediris_supplement_allowed = fields.Boolean(
        string='Supplement Allowed',
        help='Indicates whether a financial supplement above the standard tariff '
             'is allowed to be charged to this patient based on their insurance status.'
    )
    mediris_last_mutual_check_date = fields.Date(
        string='Last Mutual Fund Check Date',
        help='Date when the patient\'s mutual fund and insurability data '
             'was last verified or synchronized with the mutuality database in Mediris.'
    )
    mediris_date_of_death = fields.Date(
        string='Date of Death',
        help='Date of death of the patient as recorded in Mediris. '
             'If filled, the patient is deceased and should not receive active appointments.'
    )
    mediris_gmd_start_date = fields.Date(
        string='GMD Start Date',
        help='Start date of the Global Medical Dossier (GMD / Globaal Medisch Dossier). '
             'The GMD entitles the patient to a reduced co-payment for GP consultations.'
    )
    mediris_gmd_end_date = fields.Date(
        string='GMD End Date',
        help='Expiry date of the patient\'s Global Medical Dossier (GMD). '
             'After this date the GMD must be renewed to maintain the reduced co-payment benefit.'
    )
    mediris_gmd_gp = fields.Char(
        string='GP Holding GMD',
        help='Name of the general practitioner who is the official holder of '
             'this patient\'s Global Medical Dossier (GMD) in Mediris.'
    )
    mediris_sumehr_date = fields.Date(
        string='Sumehr Date',
        help='Date of the most recent Sumehr (Summarised Electronic Health Record) '
             'generated for this patient in Mediris.'
    )
    mediris_sumehr_author = fields.Char(
        string='Sumehr Author',
        help='Name of the healthcare professional who authored '
             'the most recent Sumehr document for this patient.'
    )
    mediris_sumehr_shared = fields.Boolean(
        string='Sumehr Shared',
        help='Indicates whether the patient\'s Sumehr has been shared '
             'with the Vitalink health platform, making it accessible to other healthcare providers.'
    )
    surgery_case_ids = fields.One2many('clinic.surgery.case', 'patient_id', string='Surgery Cases',
        help='All surgery cases where this partner is the patient. '
             'Used to keep post-op follow-up stats accurate and stored.')