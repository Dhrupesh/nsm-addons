# -*- coding: utf-8 -*-
##############################################################################
#
#    Copyright 2016 Magnus www.magnus.nl
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
#import pdb; pdb.set_trace()
import time
from openerp.osv import fields, osv, orm
from openerp.tools.translate import _
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT, DATETIME_FORMATS_MAP, float_compare
import openerp.addons.decimal_precision as dp
from openerp import netsvc


class hon_issue(orm.Model):

    _name = "hon.issue"

    def _invoiced_rate(self, cursor, user, ids, name, arg, context=None):
        res = {}
        for issue in self.browse(cursor, user, ids, context=context):
            if issue.invoiced:
                res[issue.id] = 100.0
                continue
            tot = 0.0
            for invoice in issue.invoice_ids:
                if invoice.state not in ('draft', 'cancel'):
                    tot += invoice.amount_untaxed
            if tot:
                res[issue.id] = min(100.0, tot * 100.0 / (issue.amount_untaxed or 1.00))
            else:
                res[issue.id] = 0.0
        return res

    def _invoice_exists(self, cursor, user, ids, name, arg, context=None):
        res = {}
        for issue in self.browse(cursor, user, ids, context=context):
            res[issue.id] = False
            if issue.invoice_ids:
                res[issue.id] = True
        return res

    def _invoiced(self, cursor, user, ids, name, arg, context=None):
        res = {}
        for issue in self.browse(cursor, user, ids, context=context):
            res[issue.id] = True
            invoice_existence = False
            for invoice in issue.invoice_ids:
                if invoice.state!='cancel':
                    invoice_existence = True
                    if invoice.state != 'paid':
                        res[issue.id] = False
                        break
            if not invoice_existence or issue.state == 'manual':
                res[issue.id] = False
        return res

    def _invoiced_search(self, cursor, user, obj, name, args, context=None):
        if not len(args):
            return []
        clause = ''
        issue_clause = ''
        no_invoiced = False
        for arg in args:
            if (arg[1] == '=' and arg[2]) or (arg[1] == '!=' and not arg[2]):
                clause += 'AND inv.state = \'paid\''
            else:
                clause += 'AND inv.state != \'cancel\' AND issue.state != \'cancel\'  AND inv.state <> \'paid\'  AND rel.issue_id = issue.id '
                issue_clause = ',  hon_issue AS issue '
                no_invoiced = True

        cursor.execute('SELECT rel.issue_id ' \
                'FROM hon_issue_invoice_rel AS rel, account_invoice AS inv '+ issue_clause + \
                'WHERE rel.invoice_id = inv.id ' + clause)
        res = cursor.fetchall()
        if no_invoiced:
            cursor.execute('SELECT issue.id ' \
                    'FROM hon_issue AS issue ' \
                    'WHERE issue.id NOT IN ' \
                        '(SELECT rel.issue_id ' \
                        'FROM hon_issue_invoice_rel AS rel) and issue.state != \'cancel\'')
            res.extend(cursor.fetchall())
        if not res:
            return [('id', '=', 0)]
        return [('id', 'in', [x[0] for x in res])]

    _columns = {
        'account_analytic_id': fields.many2one('account.analytic.account', 'Title/Issue', required=True, readonly=True, states = {'draft': [('readonly', False)]},
                                                domain=[('type','!=','view'), ('portal_sub', '=', True)]),

        'name': fields.char('Description', size=64, readonly=True, states={'draft':[('readonly',False)]}),
        'company_id': fields.many2one('res.company', 'Company', required=True, change_default=True, readonly=True, states={'draft':[('readonly',False)]}),
        'hon_issue_line': fields.one2many('hon.issue.line', 'issue_id', 'Hon Lines', readonly=True, states={'draft':[('readonly',False)]}),
        'state': fields.selection([
            ('draft','Draft'),
            ('open','Open'),
            ('manual', 'Invoiced'),
            ('cancel','Cancelled'),
            ('done', 'Done'),
            ],'Status', select=True, readonly=True,
            help=' * The \'Draft\' status is used when a user is encoding a new and unconfirmed Honorarium Issue. \
            \n* The \'Open\' status is used when user create invoice.\
            \n* The \'Cancelled\' status is used when user cancel Honorarium Issue.'),
        'comment': fields.text('Additional Information'),
        'invoice_ids': fields.many2many('account.invoice', 'hon_issue_invoice_rel', 'issue_id', 'invoice_id',
                                        'Invoices', readonly=True,
                                        help="This is the list of invoices that have been generated for this issue. The same issue may have been invoiced in several times (by line for example)."),
        'invoiced_rate': fields.function(_invoiced_rate, string='Invoiced Ratio', type='float'),
        'invoiced': fields.function(_invoiced, string='Paid',
                                    fnct_search=_invoiced_search, type='boolean',
                                    help="It indicates that an invoice has been paid."),
        'invoice_exists': fields.function(_invoice_exists, string='Invoiced',
                                          fnct_search=_invoiced_search, type='boolean',
                                          help="It indicates that hon issue has at least one invoice."),
    }

    _defaults = {
        'company_id': lambda self,cr,uid,c:
            self.pool.get('res.company')._company_default_get(cr, uid, 'hon.issue', context=c),
        'state': 'draft',
    }
    _sql_constraints = [
        ('account_analytic_company_uniq', 'unique (account_analytic_id, company_id)', 'The Issue must be unique per company !'),
    ]


    def onchange_analytic_ac(self, cr, uid, ids, analytic, context={}):
        res = {}
        war = {}
        if not ids:
            return res
        iss_obj = self.browse(cr,uid,ids)
        analytic_account = self.pool['account.analytic.account'].browse(cr, uid, analytic, context)
        res['name'] = analytic_account.name
        llist = []
        if iss_obj[0].hon_issue_line:
            for line in iss_obj[0].hon_issue_line:
                if line.activity_id:
                    llist.append((1, line.id, {'activity_id': [],}))
                    res['hon_issue_line'] = llist
                    war['title'] = 'Let op!'
                    war['message'] = 'U heeft de Titel/Nummer aangepast. Nu moet u opnieuw Redacties selecteren in de HONregel(s)'
        return {'value': res, 'warning': war}

    """def manual_invoice(self, cr, uid, ids, context=None):
            #create invoices for the given sales orders (ids), and open the form
            #view of one of the newly created invoices

        mod_obj = self.pool.get('ir.model.data')
        wf_service = netsvc.LocalService("workflow")

        # create invoices through the sales orders' workflow
        inv_ids0 = set(inv.id for sale in self.browse(cr, uid, ids, context) for inv in sale.invoice_ids)
        for id in ids:
            wf_service.trg_validate(uid, 'sale.order', id, 'manual_invoice', cr)
        inv_ids1 = set(inv.id for sale in self.browse(cr, uid, ids, context) for inv in sale.invoice_ids)
        # determine newly created invoices
        new_inv_ids = list(inv_ids1 - inv_ids0)

        res = mod_obj.get_object_reference(cr, uid, 'account', 'invoice_form')
        res_id = res and res[1] or False,

        return {
            'name': _('Customer Invoices'),
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': [res_id],
            'res_model': 'account.invoice',
            'context': "{'type':'out_invoice'}",
            'type': 'ir.actions.act_window',
            'nodestroy': True,
            'target': 'current',
            'res_id': new_inv_ids and new_inv_ids[0] or False,
        }"""

    def action_view_invoice(self, cr, uid, ids, context=None):
        '''
        This function returns an action that display existing invoices of given hon issue ids. It can either be a in a list or in a form view, if there is only one invoice to show.
        '''
        mod_obj = self.pool.get('ir.model.data')
        act_obj = self.pool.get('ir.actions.act_window')

        result = mod_obj.get_object_reference(cr, uid, 'account', 'action_invoice_tree2')
        id = result and result[1] or False
        result = act_obj.read(cr, uid, [id], context=context)[0]
        #compute the number of invoices to display
        inv_ids = []
        for so in self.browse(cr, uid, ids, context=context):
            inv_ids += [invoice.id for invoice in so.invoice_ids]
        #choose the view_mode accordingly
        if len(inv_ids)>1:
            result['domain'] = "[('id','in',["+','.join(map(str, inv_ids))+"])]"
        else:
            res = mod_obj.get_object_reference(cr, uid, 'account', 'invoice_supplier_form')
            result['views'] = [(res and res[1] or False, 'form')]
            result['res_id'] = inv_ids and inv_ids[0] or False
        return result

    """def action_invoice_create(self, cr, uid, ids, grouped=False, states=None, date_invoice = False, context=None):
        if states is None:
            states = ['confirmed', 'done', 'exception']
        res = False
        invoices = {}
        invoice_ids = []
        invoice = self.pool.get('account.invoice')
        obj_sale_order_line = self.pool.get('sale.order.line')
        partner_currency = {}
        if context is None:
            context = {}
        # If date was specified, use it as date invoiced, usefull when invoices are generated this month and put the
        # last day of the last month as invoice date
        if date_invoice:
            context['date_invoice'] = date_invoice
        for o in self.browse(cr, uid, ids, context=context):
            currency_id = o.pricelist_id.currency_id.id
            if (o.partner_id.id in partner_currency) and (partner_currency[o.partner_id.id] <> currency_id):
                raise osv.except_osv(
                    _('Error!'),
                    _('You cannot group sales having different currencies for the same partner.'))

            partner_currency[o.partner_id.id] = currency_id
            lines = []
            for line in o.order_line:
                if line.invoiced:
                    continue
                elif (line.state in states):
                    lines.append(line.id)
            created_lines = obj_sale_order_line.invoice_line_create(cr, uid, lines)
            if created_lines:
                invoices.setdefault(o.partner_invoice_id.id or o.partner_id.id, []).append((o, created_lines))
        if not invoices:
            for o in self.browse(cr, uid, ids, context=context):
                for i in o.invoice_ids:
                    if i.state == 'draft':
                        return i.id
        for val in invoices.values():
            if grouped:
                res = self._make_invoice(cr, uid, val[0][0], reduce(lambda x, y: x + y, [l for o, l in val], []), context=context)
                invoice_ref = ''
                origin_ref = ''
                for o, l in val:
                    invoice_ref += (o.client_order_ref or o.name) + '|'
                    origin_ref += (o.origin or o.name) + '|'
                    self.write(cr, uid, [o.id], {'state': 'progress'})
                    cr.execute('insert into sale_order_invoice_rel (order_id,invoice_id) values (%s,%s)', (o.id, res))
                #remove last '|' in invoice_ref
                if len(invoice_ref) >= 1:
                    invoice_ref = invoice_ref[:-1]
                if len(origin_ref) >= 1:
                    origin_ref = origin_ref[:-1]
                invoice.write(cr, uid, [res], {'origin': origin_ref, 'name': invoice_ref})
            else:
                for order, il in val:
                    res = self._make_invoice(cr, uid, order, il, context=context)
                    invoice_ids.append(res)
                    self.write(cr, uid, [order.id], {'state': 'progress'})
                    cr.execute('insert into sale_order_invoice_rel (order_id,invoice_id) values (%s,%s)', (order.id, res))
        return res"""

    def action_invoice_end(self, cr, uid, ids, context=None):
        for this in self.browse(cr, uid, ids, context=context):
            for line in this.hon_issue_line:
                if line.state == 'confirmed':
                    line.write({'state': 'progress'})
    #        if this.state == 'invoice_except':
    #            this.write({'state': 'progress'})
        return True

    def action_invoice_cancel(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'state': 'manual'}, context=context)
        return True

    #def action_button_confirm(self, cr, uid, ids, context=None):
    #    assert len(ids) == 1, 'This option should only be used for a single id at a time.'
    #    wf_service = netsvc.LocalService('workflow')
    #    wf_service.trg_validate(uid, 'hon.issue', ids[0], 'issue_confirm', cr)
    #    return True

    def unlink(self, cr, uid, ids, context=None):
        issues = self.read(cr, uid, ids, ['state'], context=context)
        unlink_ids = []
        for s in issues:
            if s['state'] in ['draft', 'cancel']:
                unlink_ids.append(s['id'])
            else:
                raise osv.except_osv(_('Invalid Action!'), _('In order to delete a confirmed issue, you must cancel it before!'))

        return osv.osv.unlink(self, cr, uid, unlink_ids, context=context)

    def action_wait(self, cr, uid, ids, context=None):
        context = context or {}
        for o in self.browse(cr, uid, ids):
            if not o.hon_issue_line:
                raise osv.except_osv(_('Error!'),_('You cannot confirm a hon issue which has no line.'))
            self.write(cr, uid, [o.id], {'state': 'open', })
            self.pool.get('hon.issue.line').button_confirm(cr, uid, [x.id for x in o.hon_issue_line])
        return True

    def action_unwait(self, cr, uid, ids, context=None):
        context = context or {}
        for o in self.browse(cr, uid, ids):
            if not o.hon_issue_line:
                raise osv.except_osv(_('Error!'),_('You cannot unconfirm a hon issue which has no line.'))
            self.write(cr, uid, [o.id], {'state': 'draft', })
            self.pool.get('hon.issue.line').button_unconfirm(cr, uid, [x.id for x in o.hon_issue_line])
        return True



class hon_issue_line(orm.Model):

    _name = "hon.issue.line"

    def _amount_line(self, cr, uid, ids, prop, unknow_none, unknow_dict):
        res = {}
        for line in self.browse(cr, uid, ids):
            price = line.price_unit * line.quantity
            res[line.id] = price
        return res

    def _fnct_line_invoiced(self, cr, uid, ids, field_name, args, context=None):
        res = dict.fromkeys(ids, False)
        for this in self.browse(cr, uid, ids, context=context):
            res[this.id] = this.invoice_lines and \
                all(iline.invoice_id.state != 'cancel' for iline in this.invoice_lines)
        return res

    def _hon_issue_lines_from_invoice(self, cr, uid, ids, context=None):
        # direct access to the m2m table is the less convoluted way to achieve this (and is ok ACL-wise)
        cr.execute("""SELECT DISTINCT hil.id FROM hon_issue_invoice_rel rel JOIN
                                                  hon_issue_line hil ON (hil.issue_id = rel.issue_id)
                                    WHERE rel.invoice_id = ANY(%s)""", (list(ids),))
        return [i[0] for i in cr.fetchall()]

    _columns = {
        'sequence': fields.integer('Sequence', help="Gives the sequence of this line when displaying the honorarium issue."),
        'name': fields.char('Description', required=True, size=64),
        'page_number': fields.char('Pgnr', size=32),
        'nr_of_columns': fields.float('#Cols', digits_compute= dp.get_precision('Number of Columns'), required=True),
        'issue_id': fields.many2one('hon.issue', 'Issue Reference', ondelete='cascade', select=True),
        'partner_id': fields.many2one('res.partner', 'Partner',),
        'employee': fields.boolean('Employee',  help="It indicates that the partner is an employee."),
        'product_category_id': fields.many2one('product.category', 'Page Type',domain=[('parent_id.supportal', '=', True)]),
        'product_id': fields.many2one('product.product', 'Product', required=True,),
        'account_id': fields.many2one('account.account', 'Account', required=True, domain=[('type','<>','view'), ('type', '<>', 'closed')],
                                      help="The income or expense account related to the selected product."),
        'uos_id': fields.many2one('product.uom', 'Unit of Measure', ondelete='set null', select=True),
        'price_unit': fields.float('Unit Price', required=True, digits_compute= dp.get_precision('Product Price')),
        'quantity': fields.float('Quantity', digits_compute= dp.get_precision('Product Unit of Measure'), required=True),
        'account_analytic_id': fields.related('issue_id','account_analytic_id',type='many2one',relation='account.analytic.account', string='Editie',store=True, readonly=True ),
        'activity_id': fields.many2one('project.activity_al', 'Redactie',  ondelete='set null', select=True),
        'company_id': fields.related('issue_id','company_id',type='many2one',relation='res.company',string='Company', store=True, readonly=True),
        'price_subtotal': fields.function(_amount_line, string='Amount', type="float",
            digits_compute= dp.get_precision('Account'), store=True),
        'estimated_price': fields.float('Estimate',),
        'invoice_lines': fields.many2many('account.invoice.line', 'hon_issue_line_invoice_rel', 'hon_issue_line_id',
                                          'invoice_id', 'Invoice Lines', readonly=True),
        'invoiced': fields.function(_fnct_line_invoiced, string='Invoiced', type='boolean',
                        store={'account.invoice': (_hon_issue_lines_from_invoice, ['state'], 10),
                               'hon.issue.line': (lambda self, cr, uid, ids, ctx=None: ids, ['invoice_lines'], 10)}),
        'state': fields.selection(
            [('cancel', 'Cancelled'),
             ('draft', 'Draft'),
             ('confirmed', 'Confirmed'),
             ('progress', 'Invoiced'),
             ('done', 'Done')],
            'Status', required=True, readonly=True,
            help='* The \'Draft\' status is set when the related hon issue in draft status. \
                        \n* The \'Confirmed\' status is set when the related hon issue is confirmed. \
                        \n* The \'Exception\' status is set when the related hon issue is set as exception. \
                        \n* The \'Done\' status is set when the hon line has been picked. \
                        \n* The \'Cancelled\' status is set when a user cancel the hon issue related.'),
    }

    def _default_account_id(self, cr, uid, context=None):
        # XXX this gets the default account for the user's company,
        # it should get the default account for the invoice's company
        # however, the invoice's company does not reach this point
        if context is None:
            context = {}
        prop = self.pool.get('ir.property').get(cr, uid, 'property_account_expense_categ', 'product.category', context=context)
        return prop and prop.id or False

    _defaults = {
        'quantity': 1,
        'sequence': 10,
        'account_id': _default_account_id,
        'state': 'draft',
        'price_unit': 0.0,
    }

    #def _get_line_qty(self, cr, uid, line, context=None):
    #    if (line.issue_id.invoice_quantity=='order'):
    #        if line.product_uos:
    #            return line.product_uos_qty or 0.0
    #   return line.product_uom_qty


    def _prepare_hon_issue_line_invoice_line(self, cr, uid, line, account_id=False, context=None):
        """Prepare the dict of values to create the new invoice line for a
           honorarium line. This method may be overridden to implement custom
           invoice generation (making sure to call super() to establish
           a clean extension chain).

           :param browse_record line: hon.issue.line record to invoice
           :param int account_id: optional ID of a G/L account to force
               (this is used for returning products including service)
           :return: dict of values to create() the invoice line
        """
        res = {}
        if not line.invoiced:
            if not account_id:
                if line.product_id:
                    account_id = line.product_id.property_account_expense.id
                    if not account_id:
                        account_id = line.product_id.categ_id.property_account_expense_categ.id
                    if not account_id:
                        raise osv.except_osv(_('Error!'),
                                _('Please define expense account for this product: "%s" (id:%d).') % \
                                    (line.product_id.name, line.product_id.id,))
                else:
                    prop = self.pool.get('ir.property').get(cr, uid,
                            'property_account_expense_categ', 'product.category',
                            context=context)
                    account_id = prop and prop.id or False
            qty = line.quantity
            #pu = 0.0
            #if qty:
            #    pu = round(line.price_unit * line.quantity,
            #            self.pool.get('decimal.precision').precision_get(cr, uid, 'Product Price'))
            fpos = line.partner_id.property_account_position or False
            account_id = self.pool.get('account.fiscal.position').map_account(cr, uid, fpos, account_id)
            if not account_id:
                raise osv.except_osv(_('Error!'),
                            _('There is no Fiscal Position defined or Expense category account defined for default properties of Product categories.'))
            res = {
                'name': line.name,
                'sequence': line.sequence,
                'origin': line.issue_id.name,
                'account_id': account_id,
                'price_unit': line.price_unit,
                'quantity': qty,
                'uos_id': line.uos_id,
                'product_id': line.product_id.id or False,
                #'invoice_line_tax_id': [(6, 0, [x.id for x in line.tax_id])],
                'account_analytic_id': line.issue_id.account_analytic_id and line.issue_id.account_analytic_id.id or False,
                'activity_id': line.activity_id and line.activity_id.id or False,
            }

        return res

    def invoice_line_create(self, cr, uid, ids, context=None):
        if context is None:
            context = {}

        create_ids = []
        hon = set()
        for line in self.browse(cr, uid, ids, context=context):
            vals = self._prepare_hon_issue_line_invoice_line(cr, uid, line, False, context)
            if vals:
                inv_id = self.pool.get('account.invoice.line').create(cr, uid, vals, context=context)
                self.write(cr, uid, [line.id], {'invoice_lines': [(4, inv_id)]}, context=context)
                hon.add(line.issue_id.id)
                create_ids.append(inv_id)
        # Trigger workflow events
        wf_service = netsvc.LocalService("workflow")
        for issue_id in hon:
            wf_service.trg_write(uid, 'hon.issue', issue_id, cr)
        return create_ids

    def button_cancel(self, cr, uid, ids, context=None):
        for line in self.browse(cr, uid, ids, context=context):
            if line.invoiced:
                raise osv.except_osv(_('Invalid Action!'), _('You cannot cancel a Hon line that has already been invoiced.'))
        return self.write(cr, uid, ids, {'state': 'cancel'})

    def button_confirm(self, cr, uid, ids, context=None):
        return self.write(cr, uid, ids, {'state': 'confirmed'})

    def button_unconfirm(self, cr, uid, ids, context=None):
        return self.write(cr, uid, ids, {'state': 'draft'})

    def button_done(self, cr, uid, ids, context=None):
        wf_service = netsvc.LocalService("workflow")
        res = self.write(cr, uid, ids, {'state': 'done'})
        for line in self.browse(cr, uid, ids, context=context):
            wf_service.trg_write(uid, 'hon.issue', line.issue_id.id, cr)
        return res

    def unlink(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        """Allows to delete hon lines in draft,cancel states"""
        for rec in self.browse(cr, uid, ids, context=context):
            if rec.state not in ['draft', 'cancel']:
                raise osv.except_osv(_('Invalid Action!'), _('Cannot delete a hon line which is in state \'%s\'.') %(rec.state,))
        return super(hon_issue_line, self).unlink(cr, uid, ids, context=context)

    def partner_id_change(self, cr, uid, ids, partner_id=False,  context=None):
        if context is None:
            context = {}
        if not partner_id :
            raise osv.except_osv(_('No Partner Defined!'),_("You must first select a partner!") )
        part = self.pool.get('res.partner').browse(cr, uid, partner_id, context=context)
        result = {}
        if part.employee :
            result['employee'] = True
        else:
            result['employee'] = False
        res_final = {'value':result,}

        return res_final

    def price_quantity_change(self, cr, uid, ids, partner_id=False, price_unit=False, quantity=False, price_subtotal=False, context=None):
        if context is None:
            context = {}
        if not partner_id :
            raise osv.except_osv(_('No Partner Defined!'),_("You must first select a partner!") )
        result = {}
        if price_unit :
            if quantity :
                price = price_unit * quantity
            result['price_subtotal'] = price
        else:
            result['price_subtotal'] = price_subtotal
        res_final = {'value':result,}
        return res_final


    def product_id_change(self, cr, uid, ids, product,  partner_id=False, price_unit=False, context=None ):
        if context is None:
            context = {}
        user = self.pool.get('res.users').browse(cr, uid, uid, context=context)
        company_id = context.get('company_id', user.company_id.id)
        context = dict(context)
        context.update({'company_id': company_id, 'force_company': company_id})
        if not partner_id :
            raise osv.except_osv(_('No Partner Defined!'),_("You must first select a partner!") )
        if not product:
            raise osv.except_osv(_('No Product Defined!'),_("You must first select a Product!") )
        part = self.pool.get('res.partner').browse(cr, uid, partner_id, context=context)
        if part.lang:
            context.update({'lang': part.lang})
        result = {}
        res = self.pool.get('product.product').browse(cr, uid, product, context=context)
        a = res.property_account_expense.id
        if a:
            result['account_id'] = a
        pricelist = self.pool.get('partner.product.price').search(cr, uid, [('product_id','=',product),
                                 ('partner_id','=', partner_id), ('company_id','=', company_id )], context=context)
        if len(pricelist) >= 1 :
            price = self.pool.get('partner.product.price').browse(cr, uid, pricelist, context=context )
            if price :
                result.update( {'price_unit': price[0].price_unit} )
        else:
            result.update( {'price_unit': price_unit} )

        res_final = {'value':result,}

        return res_final

