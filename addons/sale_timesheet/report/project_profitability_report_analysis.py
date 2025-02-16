# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, tools


class ProfitabilityAnalysis(models.Model):

    _name = "project.profitability.report"
    _description = "Project Profitability Report"
    _order = 'project_id, sale_line_id'
    _auto = False

    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account', readonly=True)
    project_id = fields.Many2one('project.project', string='Project', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Project Currency', readonly=True)
    company_id = fields.Many2one('res.company', string='Project Company', readonly=True)
    user_id = fields.Many2one('res.users', string='Project Manager', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    # cost
    timesheet_unit_amount = fields.Float("Timesheet Unit Amount", digits=(16, 2), readonly=True, group_operator="sum")
    timesheet_cost = fields.Float("Timesheet Cost", digits=(16, 2), readonly=True, group_operator="sum")
    expense_cost = fields.Float("Other Cost", digits=(16, 2), readonly=True, group_operator="sum")
    # sale revenue
    order_confirmation_date = fields.Datetime('Sales Order Confirmation Date', readonly=True)
    sale_line_id = fields.Many2one('sale.order.line', string='Sale Order Line', readonly=True)
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)

    amount_untaxed_to_invoice = fields.Float("Untaxed Amount To Invoice", digits=(16, 2), readonly=True, group_operator="sum")
    amount_untaxed_invoiced = fields.Float("Untaxed Amount Invoiced", digits=(16, 2), readonly=True, group_operator="sum")
    expense_amount_untaxed_to_invoice = fields.Float("Untaxed Amount to Re-invoice", digits=(16, 2), readonly=True, group_operator="sum")
    expense_amount_untaxed_invoiced = fields.Float("Untaxed Re-invoiced Amount", digits=(16, 2), readonly=True, group_operator="sum")

    @api.model
    def _select(self):
        return """
            SELECT
                ROW_NUMBER() OVER (ORDER BY P.id, SOL.id) AS id,
                P.id AS project_id,
                P.user_id AS user_id,
                SOL.id AS sale_line_id,
                P.analytic_account_id AS analytic_account_id,
                P.partner_id AS partner_id,
                C.id AS company_id,
                C.currency_id AS currency_id,
                S.id AS sale_order_id,
                S.date_order AS order_confirmation_date,
                SOL.product_id AS product_id,
                SOL.qty_delivered_method AS sale_qty_delivered_method,
                CASE
                    WHEN SOL.qty_delivered_method = 'analytic' THEN (SOL.untaxed_amount_to_invoice / CASE COALESCE(S.currency_rate, 0) WHEN 0 THEN 1.0 ELSE S.currency_rate END)
                    ELSE 0.0
                END AS expense_amount_untaxed_to_invoice,
                CASE
                    WHEN SOL.qty_delivered_method = 'analytic' AND SOL.invoice_status = 'invoiced'
                    THEN
                        CASE
                            WHEN T.expense_policy = 'sales_price'
                            THEN (SOL.untaxed_amount_invoiced / CASE COALESCE(S.currency_rate, 0) WHEN 0 THEN 1.0 ELSE S.currency_rate END)
                            ELSE -COST_SUMMARY.expense_cost
                        END
                    ELSE 0.0
                END AS expense_amount_untaxed_invoiced,
                CASE
                    WHEN SOL.qty_delivered_method IN ('timesheet', 'manual', 'stock_move') THEN (SOL.untaxed_amount_to_invoice / CASE COALESCE(S.currency_rate, 0) WHEN 0 THEN 1.0 ELSE S.currency_rate END)
                    ELSE 0.0
                END AS amount_untaxed_to_invoice,
                CASE
                    WHEN SOL.qty_delivered_method IN ('timesheet', 'manual', 'stock_move') THEN (COALESCE(SOL.untaxed_amount_invoiced, COST_SUMMARY.downpayment_invoiced) / CASE COALESCE(S.currency_rate, 0) WHEN 0 THEN 1.0 ELSE S.currency_rate END)
                    ELSE 0.0
                END AS amount_untaxed_invoiced,
                COST_SUMMARY.timesheet_unit_amount AS timesheet_unit_amount,
                COST_SUMMARY.timesheet_cost AS timesheet_cost,
                COST_SUMMARY.expense_cost AS expense_cost
        """

    @api.model
    def _from(self):
        return """
            FROM project_project P
                JOIN res_company C ON C.id = P.company_id
                LEFT JOIN (
                    SELECT
                        project_id,
                        analytic_account_id,
                        sale_line_id,
                        SUM(timesheet_unit_amount) AS timesheet_unit_amount,
                        SUM(timesheet_cost) AS timesheet_cost,
                        SUM(expense_cost) AS expense_cost,
                        SUM(downpayment_invoiced) AS downpayment_invoiced
                    FROM (
                        SELECT
                            P.id AS project_id,
                            P.analytic_account_id AS analytic_account_id,
                            TS.so_line AS sale_line_id,
                            SUM(TS.unit_amount) AS timesheet_unit_amount,
                            SUM(TS.amount) AS timesheet_cost,
                            0.0 AS expense_cost,
                            0.0 AS downpayment_invoiced
                        FROM account_analytic_line TS, project_project P
                        WHERE TS.project_id IS NOT NULL AND P.id = TS.project_id AND P.active = 't' AND P.allow_timesheets = 't'
                        GROUP BY P.id, TS.so_line

                        UNION

                        SELECT
                            P.id AS project_id,
                            P.analytic_account_id AS analytic_account_id,
                            AAL.so_line AS sale_line_id,
                            0.0 AS timesheet_unit_amount,
                            0.0 AS timesheet_cost,
                            CASE
                                WHEN AAL.product_id != CAST((COALESCE((SELECT value FROM ir_config_parameter WHERE key='sale.default_deposit_product_id'), '-1')) as INT)
                                THEN (SUM(AAL.amount))
                                ELSE 0.0
                            END AS expense_cost,
                            0.0 AS downpayment_invoiced
                        FROM project_project P
                            LEFT JOIN account_analytic_account AA ON P.analytic_account_id = AA.id
                            LEFT JOIN account_analytic_line AAL ON AAL.account_id = AA.id
                            LEFT JOIN account_move_line RINVL ON AAL.move_id = RINVL.id
                                                                AND RINVL.parent_state = 'posted'
                                                                AND RINVL.exclude_from_invoice_tab = 'f'
                            -- Check if the AAL is not related to a reversed credit note
                            LEFT JOIN account_move RINV ON RINV.id = RINVL.move_id
                            LEFT JOIN account_move_line INVL ON INVL.move_id = RINV.reversed_entry_id
                                                            AND INVL.parent_state = 'posted'
                                                            AND INVL.exclude_from_invoice_tab = 'f'
                                                            AND INVL.product_id = RINVL.product_id

                            -- Check if it's not a bill which has been reversed
                            -- In this case, RINVL should be considered as a Vendor Bill line, and here below we search for the bill reversal.
                            LEFT JOIN account_move RBILL ON RBILL.reversed_entry_id = RINVL.move_id
                            LEFT JOIN account_move_line RBILLL ON RBILLL.move_id = RBILL.id
                                                            AND RBILLL.parent_state = 'posted'
                                                            AND RBILLL.exclude_from_invoice_tab = 'f'
                                                            AND RBILLL.product_id = RINVL.product_id

                        WHERE AAL.amount < 0.0 AND AAL.project_id IS NULL AND P.active = 't' AND P.allow_timesheets = 't'
                            AND INVL.id IS NULL -- exclude credit notes from this subquery
                            AND RBILLL.id IS NULL
                        GROUP BY P.id, AA.id, AAL.so_line, AAL.product_id

                        UNION

                        SELECT
                            P.id AS project_id,
                            P.analytic_account_id AS analytic_account_id,
                            SOLDOWN.id AS sale_line_id,
                            0.0 AS timesheet_unit_amount,
                            0.0 AS timesheet_cost,
                            0.0 AS expense_cost,
                            CASE WHEN SOLDOWN.invoice_status = 'invoiced' THEN SOLDOWN.price_reduce ELSE 0.0 END AS downpayment_invoiced
                        FROM project_project P
                            INNER JOIN sale_order_line SOL ON P.sale_line_id = SOL.id
                            INNER JOIN sale_order_line SOLDOWN ON SOLDOWN.order_id = SOL.order_id AND SOLDOWN.is_downpayment = 't'
                            LEFT JOIN sale_order_line_invoice_rel SOINV ON SOINV.order_line_id = SOLDOWN.id
                            LEFT JOIN account_move_line INVL ON SOINV.invoice_line_id = INVL.id
                                                            AND INVL.parent_state = 'posted'
                                                            AND INVL.exclude_from_invoice_tab = 'f'
                            LEFT JOIN account_move RINV ON INVL.move_id = RINV.reversed_entry_id
                            LEFT JOIN account_move_line RINVL ON RINV.id = RINVL.move_id
                                                                AND RINVL.parent_state = 'posted'
                                                                AND RINVL.exclude_from_invoice_tab = 'f'
                                                                AND RINVL.product_id = SOLDOWN.product_id
                            LEFT JOIN account_analytic_line ANLI ON ANLI.move_id = RINVL.id AND ANLI.amount < 0.0
                        WHERE ANLI.id IS NULL -- there are no credit note for this downpayment
                            AND P.active = 't' AND P.allow_timesheets = 't'
                        GROUP BY P.id, SOLDOWN.id

                        UNION

                        SELECT
                            P.id AS project_id,
                            P.analytic_account_id AS analytic_account_id,
                            SOL.id AS sale_line_id,
                            0.0 AS timesheet_unit_amount,
                            0.0 AS timesheet_cost,
                            0.0 AS expense_cost,
                            0.0 AS downpayment_invoiced
                        FROM sale_order_line SOL
                            INNER JOIN project_project P ON SOL.project_id = P.id
                        WHERE P.active = 't' AND P.allow_timesheets = 't'

                        UNION

                        SELECT
                            P.id AS project_id,
                            P.analytic_account_id AS analytic_account_id,
                            SOL.id AS sale_line_id,
                            0.0 AS timesheet_unit_amount,
                            0.0 AS timesheet_cost,
                            0.0 AS expense_cost,
                            0.0 AS downpayment_invoiced
                        FROM sale_order_line SOL
                            INNER JOIN project_task T ON SOL.task_id = T.id
                            INNER JOIN project_project P ON P.id = T.project_id
                        WHERE P.active = 't' AND P.allow_timesheets = 't'
                    ) SUB_COST_SUMMARY
                    GROUP BY project_id, analytic_account_id, sale_line_id
                ) COST_SUMMARY ON COST_SUMMARY.project_id = P.id
                LEFT JOIN sale_order_line SOL ON COST_SUMMARY.sale_line_id = SOL.id
                LEFT JOIN sale_order S ON SOL.order_id = S.id
                LEFT JOIN product_product PP on (SOL.product_id=PP.id)
                LEFT JOIN product_template T on (PP.product_tmpl_id=T.id)
        """

    @api.model
    def _where(self):
        return """
            WHERE P.active = 't' AND P.analytic_account_id IS NOT NULL
        """

    def init(self):
        tools.drop_view_if_exists(self._cr, self._table)
        query = """
            CREATE VIEW %s AS (
                %s %s %s
            )
        """ % (self._table, self._select(), self._from(), self._where())
        self._cr.execute(query)
