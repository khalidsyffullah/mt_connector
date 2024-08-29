
import io
import json
from odoo import http
from odoo.http import Controller, route, request
from odoo.tools import html_escape
from base64 import b64decode
from odoo.tools.image import image_data_uri, base64_to_image
import logging

_logger = logging.getLogger(__name__)

                                                
class ImageController(http.Controller):        
    @http.route('/woocomm/images/<int:id>/<name>', type='http', auth='public', methods=['GET'], csrf=False)
    def get_woocomm_data(self, id, name):
               
        image = http.request.env['woocommerce.product.image'].sudo().search([('id', '=', id)], limit=1)
        raw_image = base64_to_image(image.wooc_image)
        
        return http.Response(response = b64decode(image.wooc_image.decode("utf-8")), 
                             status=200,
                             content_type=self.get_image_type(raw_image.format)
                             )
    
    def get_image_type(self, img_type):
        
        image_type = {
                    "JPEG"  : "image/jpeg",
                    "PNG"   : "image/png",
                    }
        if(image_type.__contains__(img_type)):
            return image_type[img_type]
        else:
            return "image/png"