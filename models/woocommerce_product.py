# -*- coding: utf-8 -*-
import imghdr
import urllib
import base64
import requests
import json
import itertools
import logging
import time

from woocommerce import API
from urllib.request import urlopen
from odoo.exceptions import UserError, MissingError
from odoo import models, api, fields, _
from odoo.tools import config
from bs4 import BeautifulSoup

config['limit_time_real'] = 10000000
config['limit_time_cpu'] = 600

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    woocomm_variant_id = fields.Char('WooCommerce ID')
    woocomm_regular_price = fields.Float('WooCommerce Regular Price')
    woocomm_varient_description = fields.Text('WooCommerce Variant Description')
    woocomm_sale_price = fields.Float('WooCommerce Sales Price')
    woocomm_stock_quantity = fields.Float("WooCommerce Stock Quantity")
    woocomm_stock_status = fields.Char("WooCommerce Stock Status")

    is_exported = fields.Boolean('Synced In WooCommerce', default=False)

    woocomm_instance_id = fields.Many2one('woocommerce.instance', ondelete='cascade')
    wooc_product_image_id = fields.Many2one('woocommerce.product.image')
    woocomm_variant_ids = fields.One2many("woocommerce.product.variant", "product_variant_id")

    def _compute_product_price_extra(self):
        for product in self:
            if product.woocomm_variant_id:
                product.price_extra = product.woocomm_regular_price - product.list_price  # to remove the base price if the product is from WooCommerce
            else:
                product.price_extra = sum(product.product_template_attribute_value_ids.mapped('price_extra'))


class Product(models.Model):
    _inherit = 'product.template'

    @api.model
    def default_get(self, fields):
        res = super(Product, self).default_get(fields)
        if self.env['woocommerce.instance']._context.get('woocomm_instance_id'):
            res['woocomm_instance_id'] = self.env['woocommerce.instance']._context.get('woocomm_instance_id')

        res['detailed_type'] = "product"

        return res

    wooc_id = fields.Char('WooCommerce ID')
    woocomm_regular_price = fields.Float('WooCommerce Regular Price')
    woocomm_sale_price = fields.Float('WooCommerce Sale Price')
    woocomm_product_status = fields.Char('WooCommerce Product Status')
    woocomm_product_sku = fields.Char('WooCommerce Product SKU')
    woocomm_product_type = fields.Char('WooCommerce Product Type')
    woocomm_product_weight = fields.Float("WooCommerce Weight")
    woocomm_product_qty = fields.Float("WooCommerce Stock Quantity")

    is_exported = fields.Boolean('Synced In WooCommerce', default=False)
    is_woocomm_product = fields.Boolean('Is WooCommerce Product', default=False)
    is_product_active = fields.Boolean()

    woocomm_instance_id = fields.Many2one('woocommerce.instance', ondelete='cascade')
    woocomm_tag_ids = fields.Many2many("product.tag.woocommerce", relation='product_woocommerce_tags_rel',
                                       string="Tags")
    woocomm_variant_ids = fields.One2many("woocommerce.product.variant", "product_template_id")
    woocomm_image_ids = fields.One2many("woocommerce.product.image", "product_template_id")

    def init_wc_api(self, wooc_instance):
        if wooc_instance.is_authenticated:
            try:
                woo_api = API(
                    url=wooc_instance.shop_url,
                    consumer_key=wooc_instance.wooc_consumer_key,
                    consumer_secret=wooc_instance.wooc_consumer_secret,
                    wp_api=True,
                    version=wooc_instance.wooc_api_version
                )
                req_data = woo_api.get("")

                return woo_api
            except Exception as error:
                raise UserError(_("Please check your connection and try again"))
        else:
            raise UserError(
                _("Connection Instance needs to authenticate first. \n Please try after authenticating connection!!!"))

    def get_all_products(self, wooc_instance, limit=100):
        woo_api = self.init_wc_api(wooc_instance)

        url = "products"
        get_next_page = True
        page = 1
        while get_next_page:
            try:
                products = woo_api.get(url, params={'orderby': 'id', 'order': 'asc', 'per_page': limit, 'page': page})
                page += 1

            except Exception as error:
                _logger.info('\n\n\n\n  Error Products on page=  %s \n\n\n\n' % (page))
                time.sleep(2)
                continue

            if products.status_code == 200:
                if products.content:
                    parsed_products = products.json()
                    for product in parsed_products:
                        yield product

                    if len(parsed_products) < limit:
                        get_next_page = False
                else:
                    get_next_page = False
            else:
                get_next_page = False

    def get_all_products_variants(self, p_id, wooc_instance, limit=20):
        woo_api = self.init_wc_api(wooc_instance)

        url = "products/%s/variations" % p_id
        get_next_page = True
        page = 1
        while get_next_page:
            try:
                products = woo_api.get(url, params={'orderby': 'id', 'order': 'asc', 'per_page': limit, 'page': page})
                page += 1

            except Exception as error:
                _logger.info('\n\n\n\n  Error Products on page=  %s \n\n\n\n' % (page))
                time.sleep(2)
                continue

            if products.status_code == 200:
                if products.content:
                    parsed_products = products.json()
                    for product in parsed_products:
                        yield product

                    if len(parsed_products) < limit:
                        get_next_page = False
                else:
                    get_next_page = False
            else:
                get_next_page = False

    def import_product(self, wooc_instance, is_force_update=False):
        count = 0

        for p_item in self.get_all_products(wooc_instance, limit=20):
            count = count + 1
            ''' To avoid duplications of products already having wooc_id. '''

            if not is_force_update:
                exist = self.env['product.template'].sudo().search([('wooc_id', '=', p_item['id'])], limit=1)

                if exist:
                    continue

            _logger.info('\n\n\n  Importing Product =  %s -- %s \n\n' % (p_item['id'], p_item['name']))
            self.create_product(p_item, wooc_instance)

    def create_product(self, p_item, wooc_instance):

        p_tags = []

        dict_p = {}
        dict_p['wooc_id'] = p_item['id'] if p_item['id'] else ''
        dict_p['woocomm_instance_id'] = wooc_instance.id
        dict_p['name'] = p_item['name'] if p_item['name'] else ''
        dict_p['company_id'] = wooc_instance.wooc_company_id.id
        dict_p['type'] = 'product'
        dict_p['woocomm_product_status'] = p_item['status']
        dict_p['woocomm_product_type'] = p_item['type']
        dict_p['woocomm_regular_price'] = float(p_item['regular_price']) if p_item['regular_price'] else 0.0
        dict_p['woocomm_sale_price'] = float(p_item['sale_price']) if p_item['sale_price'] else 0.0

        dict_p['purchase_ok'] = True
        dict_p['sale_ok'] = True
        dict_p['is_exported'] = True
        dict_p['is_woocomm_product'] = True
        dict_p['is_product_active'] = True if p_item['status'] == 'publish' else False
        dict_p['default_code'] = p_item['sku'] if p_item['sku'] else ''

        if p_item['description']:
            dict_p['description'] = p_item['description']
            parsed_desc = BeautifulSoup(p_item['description'], 'html.parser')
            description_converted_to_text = parsed_desc.get_text()
            dict_p['description_sale'] = description_converted_to_text

        if p_item['categories']:
            for cat in p_item['categories']:

                categ = self.env['product.category'].sudo().search([('wooc_id', '=', cat['id'])], limit=1)
                if categ:
                    dict_p['categ_id'] = categ[0].id
                else:
                    dict_cat = {}
                    dict_cat['wooc_id'] = cat.get('id')
                    dict_cat['name'] = cat.get('name')
                    dict_cat['wooc_cat_slug'] = cat.get('slug')
                    dict_cat['wooc_cat_description'] = cat['description'] if cat.get('description') else ''
                    dict_cat['is_woocomm_category'] = True
                    dict_cat['is_exported'] = True
                    dict_cat['woocomm_instance_id'] = wooc_instance.id

                    category = self.env['product.category'].sudo().create(dict_cat)
                    dict_p['categ_id'] = category.id

                break

        if p_item['tags']:
            for tag_str in p_item['tags']:
                existing_tag = self.env['product.tag.woocommerce'].sudo().search(
                    [('wooc_id', '=', tag_str['id']), ('woocomm_instance_id', '=', wooc_instance.id)], limit=1)
                dict_value = {}
                dict_value['wooc_id'] = tag_str['id']
                dict_value['is_woocomm_tag'] = True
                dict_value['woocomm_instance_id'] = wooc_instance.id
                dict_value['name'] = tag_str['name']

                if not existing_tag:
                    create_tag_value = self.env['product.tag.woocommerce'].sudo().create(dict_value)
                    p_tags.append(create_tag_value.id)
                else:
                    write_tag_value = existing_tag.sudo().write(dict_value)
                    p_tags.append(existing_tag.id)

        product = self.env['product.template'].sudo().search([('wooc_id', '=', p_item['id'])], limit=1)

        if not product:
            product = self.env['product.template'].sudo().create(dict_p)
        else:
            product.sudo().write(dict_p)

        product.woocomm_tag_ids = [(4, val) for val in p_tags]

        self.env.cr.commit()

        if p_item['attributes']:
            for attr in p_item['attributes']:
                # Create or get the attribute
                product_attr = self.env['product.attribute'].sudo().search(
                    [('wooc_id', '=', attr['id']), ('woocomm_instance_id', '=', wooc_instance.id)], limit=1)
                if not product_attr:
                    product_attr = self.env['product.attribute'].sudo().create({
                        'name': attr['name'],
                        'create_variant': 'always' if attr['variation'] else 'no_variant',
                        'wooc_id': attr['id'],
                        'woocomm_instance_id': wooc_instance.id,
                    })

                # Create or get attribute values
                attr_values = []
                for option in attr['options']:
                    attr_value = self.env['product.attribute.value'].sudo().search([
                        ('name', '=', option),
                        ('attribute_id', '=', product_attr.id),
                        ('woocomm_instance_id', '=', wooc_instance.id)
                    ], limit=1)
                    if not attr_value:
                        attr_value_data = {
                            'name': option,
                            'attribute_id': product_attr.id,
                            'woocomm_attribute_id': product_attr.id,
                            'woocomm_instance_id': wooc_instance.id,
                        }
                        # Safely try to create the attribute value
                        try:
                            attr_value = self.env['product.attribute.value'].sudo().create(attr_value_data)
                        except ValueError as e:
                            _logger.error(f"Error creating attribute value: {e}")
                            # If creation fails, try to find an existing one
                            attr_value = self.env['product.attribute.value'].sudo().search([
                                ('name', '=', option),
                                ('attribute_id', '=', product_attr.id)
                            ], limit=1)
                            if not attr_value:
                                _logger.error(f"Could not create or find attribute value for {option}")
                                continue

                    if attr_value:
                        attr_values.append(attr_value.id)

                # Create or update product template attribute line
                if attr_values:
                    template_attr_line = self.env['product.template.attribute.line'].sudo().search([
                        ('attribute_id', '=', product_attr.id),
                        ('product_tmpl_id', '=', product.id)
                    ], limit=1)

                    if not template_attr_line:
                        self.env['product.template.attribute.line'].sudo().create({
                            'attribute_id': product_attr.id,
                            'product_tmpl_id': product.id,
                            'value_ids': [(6, 0, attr_values)],
                        })
                    else:
                        template_attr_line.write({
                            'value_ids': [(6, 0, attr_values)],
                        })
        # syn product images
        if p_item['images']:
            # set first image as main image
            main_image = True
            for image in p_item['images']:
                if image['src']:
                    self.import_product_images_sync(image, product, False, main_image)
                    main_image = False

        if p_item['variations']:
            self.create_product_variations(product, wooc_instance)
        else:
            product_variant = self.env['product.product'].sudo().search([('product_tmpl_id', '=', product.id)])
            if product_variant:
                product_variant.sudo().write({'woocomm_variant_id': p_item['id'],
                                              'woocomm_instance_id': wooc_instance.id,
                                              'is_exported': True})

            product.sudo().write({
                'list_price': float(p_item['price']) if p_item['price'] else 0.0,
                'weight': p_item['weight'] if p_item['weight'] else '',
            })

        self.env.cr.commit()

    def create_product_variations(self, product, wooc_instance):

        product_variant = self.env['product.product'].sudo().search([('product_tmpl_id', '=', product.id)])

        for variant in self.get_all_products_variants(product.wooc_id, wooc_instance, limit=20):
            variant_options = []
            if variant['attributes']:
                for v_attr in variant['attributes']:
                    variant_options.append(v_attr['option'])

            for v_item in product_variant:
                if v_item.product_template_attribute_value_ids:
                    list_values = []
                    for rec in v_item.product_template_attribute_value_ids:
                        list_values.append(rec.name)
                    if set(variant_options).issubset(list_values):
                        v_item.default_code = variant['sku']
                        v_item.is_exported = True
                        v_item.taxes_id = [(6, 0, [])]

                        v_item.woocomm_instance_id = wooc_instance.id
                        v_item.woocomm_variant_id = variant['id']
                        v_item.woocomm_regular_price = float(variant['regular_price']) if variant[
                            'regular_price'] else 0.0
                        v_item.woocomm_sale_price = float(variant['sale_price']) if variant['sale_price'] else 0.0
                        v_item.woocomm_varient_description = variant['description']
                        v_item.woocomm_stock_quantity = variant['stock_quantity']
                        v_item.woocomm_stock_status = variant['stock_status']

                        if variant['image']:
                            if variant['image']['src']:
                                self.import_product_images_sync(variant['image'], v_item, True)

                            self.env.cr.commit()
                        break

            self.wooc_variations_kanban(variant, product)

        self.env.cr.commit()

    def export_product(self, wooc_instance, force_update_product=False, force_update_image=False):
        woo_api = self.init_wc_api(wooc_instance)
        is_product_exported = False

        selected_ids = self.env.context.get('active_ids', [])
        products_ids = self.sudo().search([('id', 'in', selected_ids)])

        if not products_ids:
            raise UserError(_("Please select products!!!"))

        for product in products_ids:

            force_create_kanban = False

            try:
                #Condition to create only New Product
                if not force_update_product and product.is_exported:
                    continue

                data = self.product_export_data_generate(wooc_instance, product)
                if data["type"] == 'simple':
                    # add quantity if product type is simple
                    simple_product = self.env['product.product'].sudo().search([('product_tmpl_id', '=', product.id)])
                    stock_quantity = self.env['stock.quant'].sudo().search(
                        [('product_id', '=', simple_product.id), ('inventory_quantity_set', '=', True)])
                    data.update(
                        {"manage_stock": True, "stock_quantity": stock_quantity.quantity if stock_quantity else 0})

                _logger.info('\n\n\n\n  export_product=  %s \n\n\n\n' % (data))

                if product.wooc_id and product.is_exported:
                    result = woo_api.put("products/%s" % product.wooc_id, data)

                    if result.status_code in [400, 404]:
                        result = woo_api.post("products", data)
                        # remove old variant_id if product not in woocommerce
                        self.env['product.product'].sudo().search([('product_tmpl_id', '=', product.id)]).write(
                            {'woocomm_variant_id': False, 'is_exported': False})
                        self.env['woocommerce.product.image'].sudo().search(
                            [('product_template_id', '=', product.id)]).write(
                            {'is_image_synced': False, 'is_variation_update': False, 'update_only': True})
                        force_create_kanban = True
                        self.env.cr.commit()

                    result = result.json()
                else:
                    result = woo_api.post("products", data).json()
                    force_create_kanban = True

                if result:
                    is_product_exported = True

                    product.wooc_id = result['id']
                    product.woocomm_regular_price = result['regular_price']
                    product.woocomm_sale_price = result['sale_price']
                    product.is_woocomm_product = True
                    product.woocomm_instance_id = wooc_instance.id
                    product.is_exported = True
                    product.is_product_active = True
                    product.woocomm_product_status = "publish"
                    product.woocomm_product_type = result['type']
                    product.default_code = result['sku'] if result['sku'] else ''

                    self.env.cr.commit()
                #create variations
                self.wooc_variations_create(wooc_instance, product)

                if len(product.product_variant_ids) > 1 and (
                        len(product.product_variant_ids) != len(product.woocomm_variant_ids)):
                    #if kanban missing or not created
                    force_create_kanban = True

                if force_create_kanban or not force_update_product:
                    if product.attribute_line_ids and len(product.product_variant_ids) > 1:
                        self.wooc_variations_kanban_create(wooc_instance, product)
                    else:
                        _logger.info("\n\n\nNo Attribute\n\n")

                if force_update_product and force_update_image:
                    self.product_image_export(product)

                _logger.info("\n\n\nProduct created/updated successfully\n\n")

            except Exception as error:
                _logger.info("\n\n\n\n Product creation/updation Failed")
                _logger.info('\n\n\n\n Error message: -- %s \n\n\n\n\n' % error)
                raise UserError(_("Please check your connection and try again"))

        if not is_product_exported:
            raise UserError(
                _("No new Product to Export..!! \nIf trying to export existing product, please tick Force Update Product"))

    def wooc_variations_create(self, wooc_instance, product):
        woo_api = self.init_wc_api(wooc_instance)
        product_variant = self.env['product.product'].sudo().search([('product_tmpl_id', '=', product.id)])
        product_wooc_id = product.wooc_id

        for variant in product_variant:
            has_attribute = False
            stock_quantity = self.env['stock.quant'].sudo().search(
                [('product_id', '=', variant.id), ('inventory_quantity_set', '=', True)])

            if not variant.woocomm_variant_id and not variant.is_exported:
                data = {"regular_price": "%s" % variant.lst_price, "manage_stock": True,
                        "stock_quantity": stock_quantity.quantity if stock_quantity else 0}
                attr_list = []

                if variant.product_template_attribute_value_ids:
                    has_attribute = True
                    for rec in variant.product_template_attribute_value_ids:
                        attr_list.append({"id": rec.attribute_id.wooc_id, "option": rec.name, })

                    data.update({"attributes": attr_list})

                wc_variation = woo_api.post("products/%s/variations" % product_wooc_id, data).json()

                if wc_variation:
                    wooc_variant = self.env['woocommerce.product.variant'].sudo().search(
                        [('product_template_id', '=', product.id), ("product_variant_id", "=", variant.id)])
                    data = {"wooc_id": wc_variation["id"], "product_template_id": product.id,
                            "product_variant_id": variant.id, "is_manage_stock": wc_variation["manage_stock"],
                            "wooc_stock_quantity": wc_variation["stock_quantity"], }

                    if wooc_variant:
                        wooc_variant.write(data)
                    else:
                        #create variant only if attribute exist
                        if has_attribute:
                            self.env['woocommerce.product.variant'].sudo().create(data)

                    variant.write({'woocomm_variant_id': wc_variation["id"],
                                   'woocomm_regular_price': wc_variation["regular_price"],
                                   'woocomm_sale_price': wc_variation["sale_price"],
                                   'is_exported': True})
        self.env.cr.commit()

    def wooc_variations_kanban_create(self, wooc_instance, product):

        for variation in self.get_all_products_variants(product.wooc_id, wooc_instance, limit=20):
            self.wooc_variations_kanban(variation, product)

    def wooc_variations_kanban(self, variation, product):
        v_name = ""
        variant_options = []
        if variation['attributes']:
            for v_attr in variation['attributes']:
                variant_options.append(v_attr['option'])
            v_name = " x ".join(variant_options)

        data = {"wooc_id": variation["id"],
                "name": v_name,
                "wooc_sku": variation["sku"],
                "wooc_regular_price": variation["regular_price"],
                "wooc_stock_quantity": variation["stock_quantity"],
                "wooc_stock_status": variation["stock_status"],
                "wooc_variant_description": variation["description"],
                "is_enabled": True,
                "is_manage_stock": variation["manage_stock"],
                "product_template_id": product.id,
                }

        p_variant = self.env['product.product'].sudo().search(
            [('product_tmpl_id', '=', product.id), ("woocomm_variant_id", "=", variation["id"])])
        if p_variant:
            data.update({"product_variant_id": p_variant.id})
            variant_exist = self.env['woocommerce.product.variant'].sudo().search(
                [('product_template_id', '=', product.id), ("product_variant_id", "=", p_variant.id)])
        else:
            variant_exist = self.env['woocommerce.product.variant'].sudo().search(
                [('product_template_id', '=', product.id), ("wooc_id", "=", variation["id"])])

        if variant_exist:
            # Check if the existing variant's SKU matches the variation SKU
            if variant_exist.wooc_sku == variation["sku"]:
                # Check if the wooc_id matches the variation's wooc_id
                if variant_exist.wooc_id == variation["id"]:
                    variant_exist.write(data)

                else:
                    self.env.cr.commit()

        else:
            self.env['woocommerce.product.variant'].sudo().create(data)

        self.env.cr.commit()

    def product_export_data_generate(self, wooc_instance, product):

        data = {'name': "%s" % product.name,
                'type': "simple",
                'status': "publish",
                'description': product.description or "",
                'regular_price': "%s" % product.list_price,
                }

        if product.categ_id:
            if product.categ_id.wooc_id:
                data.update({"categories": [{"id": product.categ_id.wooc_id, "name": product.categ_id.name}]})

        option_list = []
        if product.attribute_line_ids:
            for attr in product.attribute_line_ids:
                val_list = []
                if not attr.attribute_id.wooc_id:
                    self.env['product.attribute'].wooc_attribute_create(wooc_instance, attr.attribute_id)

                for val in attr.value_ids:
                    val_list.append(val.name)

                attr_vals = {
                    "id": attr.attribute_id.wooc_id,
                    "options": val_list,
                    'visible': True,
                    'variation': True if len(val_list) > 1 else False,
                }
                if attr_vals["variation"]:
                    data["type"] = "variable"

                option_list.append(attr_vals)

            data.update({"attributes": option_list})

        return data

    #To update images to the woocommerce, 
    def product_image_export(self, product):
        image_list = self.env['woocommerce.product.image'].sudo().search([('product_template_id', '=', product.id), ])
        woo_api = self.init_wc_api(product.woocomm_instance_id)
        extra_check = False

        w_product = woo_api.get("products/%s" % (str(product.wooc_id)))
        if w_product.status_code == 200:
            w_product = w_product.json()

            if len(image_list):
                image_id_list = []
                new_data = {"images": [], }
                for image in image_list:
                    if requests.get(product.woocomm_instance_id.shop_url + "post?p=%s" % image.wooc_id):
                        if image.is_main_image:
                            new_data['images'].insert(0, {'id': image.wooc_id})
                        else:
                            new_data['images'].append({'id': image.wooc_id})
                    else:
                        extra_check = True
                        image_id_list.append(image.id)
                        image.is_image_synced = False

                if extra_check:
                    image_list_new = self.env['woocommerce.product.image'].sudo().search(
                        [('id', 'in', image_id_list), ])
                    for image in image_list_new:
                        if requests.get(product.woocomm_instance_id.shop_url + "post?p=%s" % image.wooc_id):
                            new_data['images'].append({'id': image.wooc_id})

                img_update = woo_api.put("products/%s" % (product.wooc_id), new_data)

                if img_update.status_code == 400:
                    _logger.info('\n\n\n\n 400 Error: -- %s \n\n\n\n\n' % img_update.json())

                if img_update.status_code == 200:
                    image_list = self.env['woocommerce.product.image'].sudo().search(
                        [('product_template_id', '=', product.id), ])
                    var_img_data = {"update": [], }
                    for image in image_list:
                        for var_img in image.product_image_variant_ids:
                            var_img_data["update"].append(
                                {"id": var_img.woocomm_variant_id, "image": {"id": image['wooc_id']}})

                    img_update = woo_api.put("products/%s/variations/batch" % (str(product.wooc_id)), var_img_data)

        return

    def set_product_status(self):
        ''' Enable or Disable Product'''
        woo_api = self.init_wc_api(self.woocomm_instance_id)

        status = self.env.context.get('status')

        product = woo_api.get("products/%s" % self.wooc_id, )
        if product.status_code == 404:
            self.is_product_active = False
            self.is_exported = False
            self.woocomm_product_status = 'draft'
            self.env.cr.commit()

            raise MissingError(_("Product Not Exist in WooCommerce, Please export first!!!"))

        data = {"status": status, }

        try:
            result = woo_api.put("products/%s" % self.wooc_id, data)

            if result.status_code == 200:
                result_json = result.json()
                self.woocomm_product_status = result_json['status']
                self.is_product_active = True if result_json['status'] == 'publish' else False

        except Exception as error:
            _logger.info("Product Enable/Disable failed!! \n\n %s" % error)
            raise UserError(_("Please check your connection and try again"))

    def get_wooc_product_data(self, product_id, wooc_instance):
        woo_api = self.init_wc_api(wooc_instance)
        wc_product = woo_api.get("products/%s" % product_id, )

        if wc_product.status_code == 200:
            if wc_product.content:
                product_data = wc_product.json()
                self.create_product(product_data, wooc_instance)

        return False

    def import_product_images_sync(self, image, product, is_variant=False, is_main_image=False):
        try:
            response = requests.get(image['src'])

            if imghdr.what(None, response.content) != 'webp':
                image_data = base64.b64encode(requests.get(image['src']).content)
                product_template_id = product.product_tmpl_id.id if is_variant else product.id
                img_vals = {"wooc_id": image['id'],
                            "name": image['name'],
                            "wooc_url": image['src'],
                            "wooc_image": image_data,
                            "product_template_id": product_template_id,
                            "is_image_synced": True,
                            "is_variation_update": False,
                            "is_import_image": True,
                            "is_main_image": is_main_image,
                            }

                ext_image = self.env['woocommerce.product.image'].sudo().search(
                    [('wooc_id', '=', img_vals['wooc_id']), ('product_template_id', '=', product_template_id)], limit=1)

                if is_variant:
                    ext_id_list = [v_id.id for v_id in ext_image.product_image_variant_ids]
                    if int(product.id) not in ext_id_list:
                        id_list = []
                        id_list.append((4, int(product.id)))
                        img_vals.update({'product_image_variant_ids': id_list})

                if not ext_image:
                    ext_image = self.env['woocommerce.product.image'].sudo().create(img_vals)
                else:
                    ext_image.sudo().write(img_vals)

                self.env.cr.commit()
        except Exception as error:
            _logger.info('\n\n\n\n  variant image error =  %s \n\n\n\n' % (error))
            pass

    def woocomm_product_quantity_update(self, wooc_instance):
        woo_api = self.init_wc_api(wooc_instance)

        selected_ids = self.env.context.get('active_ids', [])
        products_ids = self.sudo().search([('id', 'in', selected_ids)])

        if not products_ids:
            raise UserError(_("Please select products!!!"))

        var_quant_data = {"update": [], }
        for product in products_ids:
            p_type = product.woocomm_product_type
            p_variants = self.env['product.product'].sudo().search([('product_tmpl_id', '=', product.id)])
            for variant in p_variants:
                stock_quantity = self.env['stock.quant'].sudo().search(
                    [('product_id', '=', variant.id), ('inventory_quantity_set', '=', True)])
                var_quant_data["update"].append(
                    {"id": variant.woocomm_variant_id if p_type == "variable" else product.wooc_id,
                     "stock_quantity": stock_quantity.quantity if stock_quantity else 0, "manage_stock": True})

            if p_type == "variable":
                stock_quantity_update = woo_api.put("products/%s/variations/batch" % (str(product.wooc_id)),
                                                    var_quant_data)
            elif p_type == "simple":
                stock_quantity_update = woo_api.put("products/batch", var_quant_data)


class ProductTag(models.Model):
    _description = "Product Tag"
    _name = 'product.tag.woocommerce'

    wooc_id = fields.Char('WooCommerce ID')
    name = fields.Char('Tag name')
    is_woocomm_tag = fields.Boolean(string='Is WooCommerce Tag?')
    woocomm_instance_id = fields.Many2one('woocommerce.instance', ondelete='cascade')
