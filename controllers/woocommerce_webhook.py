
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



            # def woocommerce_webhook(self):
            #     try:
            #         # Get the JSON data from the request
            #         order_data = json.loads(request.httprequest.data.decode('utf-8'))
            #         woocomm_instance_id = fields.Many2one('woocommerce.instance')
            #         instance_id = woocomm_instance_id
            #
            #         # Execute in superuser context
            #         with request.env.cr.savepoint():
            #             # Use the superuser context
            #             superuser_env = request.env(user=request.env.ref('base.user_admin').id)
            #
            #             # Call the method from the SaleOrder model in superuser context
            #             SaleOrder = superuser_env['sale.order']
            #
            #             result = SaleOrder.process_woocommerce_order(order_data, instance_id)
            #
            #         # Define the file path to save the JSON file
            #         file_path = '/opt/odoo17/custom-addons/mt_odoo_woocommerce_connector/woocommerce_orders'
            #         os.makedirs(file_path, exist_ok=True)
            #
            #         # Save the JSON data as a file
            #         order_id = order_data.get('id', 'unknown_order')
            #         file_name = f'{order_id}.json'
            #         full_path = os.path.join(file_path, file_name)
            #
            #         with open(full_path, 'w') as json_file:
            #             json.dump(order_data, json_file, indent=4)
            #
            #         _logger.info(f"Order {order_id} saved successfully")
            #         return result
            #
            #     except Exception as e:
            #         _logger.error(f"Error processing webhook: {str(e)}")
            #         return {'status': 'error', 'message': str(e)}
