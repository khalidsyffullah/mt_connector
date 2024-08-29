# -*- coding: utf-8 -*-
import logging

from woocommerce import API
from odoo.exceptions import UserError, MissingError
from odoo import models, api, fields, _
from odoo.tools import config
from bs4 import BeautifulSoup
config['limit_time_real'] = 10000000
config['limit_time_cpu'] = 600


_logger = logging.getLogger(__name__)

class WooCommerceProductVariants(models.Model):
    _name = 'woocommerce.product.variant'
    _description = 'WooCommerce Product Variants'
    _order = "wooc_id desc"

    wooc_id = fields.Char(string="WooCommerce Variant id")
    name = fields.Char(string="WooCommerce Variant Name")
    wooc_variant_image = fields.Binary(string="WooCommerce Image")
    wooc_sku = fields.Char(string="WooCommerce SKU")
    wooc_regular_price = fields.Char(string="WooCommerce Regular Price")
    wooc_stock_quantity = fields.Char(string="WooCommerce Stock Quantity")    
    wooc_stock_status = fields.Selection([('instock', "In Stock"),('outofstock', "Out of Stock"),('onbackorder', "On Backorder")], string="Stock Status", default="instock") 
    wooc_v_weight = fields.Char(string="Weight")
    wooc_v_dimension_length = fields.Char(string="Length")
    wooc_v_dimension_width = fields.Char(string="Width")
    wooc_v_dimension_height = fields.Char(string="Height")
    wooc_variant_description = fields.Char(string="WooCommerce Description")
    
    is_enabled = fields.Boolean(default = True, help="Variant Enabled Or Not")
    is_manage_stock  = fields.Boolean(default = False, string="Manage Stock")  

    product_template_id = fields.Many2one('product.template', string='Product template', ondelete='cascade')
    product_variant_id = fields.Many2one('product.product', string='Product Variant', ondelete='cascade')

    def write(self, vals):
        
        if vals.__contains__('wooc_stock_quantity'):
            if vals['wooc_stock_quantity'] == 'None':
                vals['wooc_stock_quantity'] = 0
        
        super(WooCommerceProductVariants, self).write(vals)
        
        if vals.__contains__('wooc_regular_price') or vals.__contains__('wooc_sku') or \
        vals.__contains__('is_enabled') or vals.__contains__('wooc_stock_status'):
            
            self.wooc_variations_update(self)
       
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
        else :
            raise UserError(_("Connection Instance needs to authenticate first. \n Please try after authenticating connection!!!"))
        
    def wooc_variations_update(self, variant):
        product_tmpl = self.product_template_id
        product_wooc_id = product_tmpl.wooc_id
        variation_id = variant.wooc_id
            
        woo_api = self.init_wc_api(product_tmpl.woocomm_instance_id)
        
        data = {
            "regular_price": variant.wooc_regular_price,
            "sku": variant.wooc_sku,
            "stock_status": variant.wooc_stock_status,
            "status": "publish" if variant.is_enabled else "private",
            "purchasable": True if variant.is_enabled else False,
            # "manage_stock" : True if variant.is_manage_stock else False,
            # "stock_quantity" : int(variant.wooc_stock_quantity),                
            # "description" : variant.wooc_variant_description,                
        }
        
        try:
            wc_variation = woo_api.put(f"products/{product_wooc_id}/variations/{variation_id}", data, timeout=300)
            wc_variation = wc_variation.json()
        except requests.exceptions.ReadTimeout as e:
            _logger.error(f"Request to WooCommerce API timed out: {e}")
            raise
        except requests.exceptions.RequestException as e:
            _logger.error(f"Error during API request: {e}")
            raise

        product_variant = self.env['product.product'].sudo().search([
            ('product_tmpl_id', '=', product_tmpl.id), 
            ('woocomm_variant_id', '=', variation_id)
        ])

        update_data = {}
        if "regular_price" in wc_variation:
            update_data['woocomm_regular_price'] = wc_variation["regular_price"]
        if "sale_price" in wc_variation:
            update_data['woocomm_sale_price'] = wc_variation["sale_price"]

        if update_data:
            product_variant.write(update_data)
        else:
            _logger.warning(f"No price data found for WooCommerce variation ID {variation_id}")

        self.write({
            'wooc_stock_quantity': str(wc_variation.get("stock_quantity", '0')),
            'is_manage_stock': wc_variation.get("manage_stock", False),
        })

        self.env.cr.commit()
