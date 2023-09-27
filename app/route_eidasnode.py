# coding: latin-1
###############################################################################
# Copyright (c) 2023 European Commission
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
###############################################################################
"""
The PID Issuer Web service is a component of the PID Provider backend. 
Its main goal is to issue the PID in cbor/mdoc (ISO 18013-5 mdoc) and SD-JWT format.


This route_eidas-node.py file is the blueprint for the route /eidasnode of the PID Issuer Web service.
"""
import base64
import logging

from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for
)
from flask_cors import CORS

from .validate import validate_mandatory_args
from .app_config.config_countries import ConfCountries as cfgcountries
from .app_config.config_service import ConfService as cfgservice
from .redirect_func import redirect_getpid, json_post
from .lighttoken import create_request, handle_response
from .pid_func import format_pid_data, format_sd_jwt_pid_data
from .crypto_func import eccEnc, pubkeyDER

# /eidasnode blueprint
eidasnode = Blueprint('eidasnode', __name__, url_prefix='/eidasnode')
CORS(eidasnode) # enable CORS on the eidasnode blue print

# Log
logger = logging.getLogger()


# --------------------------------------------------------------------------------------------------------------------------------------
# route to /eidasnode
# @eidasnode.route('', methods=['GET','POST'])
# # route to /pid/
# @eidasnode.route('/', methods=['GET','POST'])
# def eidasnode_root():
#     """Initial eIDAS-node page. 
#     Loads country config information and renders pid_index.html so that the user can select the PID issuer country."""


#     if 'country' in request.form.keys():
#         print(cfgcountries.supported_countries[request.form.get('country')]['pid_url'])
#     return render_template('route_pid/pid-countries.html', countries = create_dict(cfgcountries.supported_countries, 'name'))
#     return "to be implemented", status.HTTP_200_OK
 

# --------------------------------------------------------------------------------------------------------------------------------------
# route to /eidasnode/lightrequest
@eidasnode.route('/lightrequest', methods=['GET'])
def getlightrequest():
    """Connects to eIDAS-Node 
    
    Get query parameters:
    + country (mandatory) - Two-letter country code according to ISO 3166-1 alpha-2.

    Return: Error to returnURL if country parameter is missing. Otherwise, create eIDAS node lightRequest and connects to the country's eIDAS node (must be defined in the local eIDAS node how to connect to the country's eIDAS node).
    """
    (b, l) = validate_mandatory_args(request.args, ['country'])
    if not b:
        return redirect_getpid(request.args.get('version'), request.args.get('returnURL'), 301, [])
    
    #session['country'] = request.args.get('country')
    return create_request(request.args.get('country'), cfgcountries.supported_countries[request.args.get('country')]['loa'])



# --------------------------------------------------------------------------------------------------------------------------------------
# route to /eidasnode/lightresponse (specific.connector.response.receiver as defined in the eidas.xml file of the local eIDAS node). 
# Contains the response to /eidasnode/lightrequest sent by the eIDAS node
@eidasnode.route('/lightresponse', methods=['POST'])
def getlightresponse():
    """Handles the response to /eidasnode/lightrequest sent by the eIDAS node
    
    Get query parameters:
    + token (mandatory) - token sent by eIDAS node.

    Return: Redirect mdoc to session['returnURL'] if no error. Otherwise redirect error to session['returnURL'],
    """
    form_keys = request.form.keys()
    # if token does not exist
    if not 'token' in form_keys:
        return redirect_getpid(session['version'], session['returnURL'], 302, [])

    (b, e) = handle_response(request.form.get('token'))
    if not b: # if error in getting the attributes
        return redirect_getpid(session['version'], session['returnURL'], 303, [('error_str', e)])
    (v, l) = validate_mandatory_args(e, cfgservice.eidasnode_pid_attributes)
    if not v: # if not all PID attributes are available
        return redirect_getpid(session['version'], session['returnURL'], 304, [])
    
    pdata = format_pid_data(e, session['country'])

    pdata1 = format_sd_jwt_pid_data(e, session['country'])

    r = json_post(cfgservice.service_url + "formatter/cbor", 
                  {'version': session['version'], 'country': session['country'], 'doctype': cfgservice.pid_doctype, 'device_publickey': session['device_publickey'], 'data':{cfgservice.pid_namespace: pdata}}).json()
    if not r['error_code'] == 0:
        return redirect_getpid(session['version'], session['returnURL'], r['error_code'], [])
    
    r1 = json_post(cfgservice.service_url + "formatter/sd-jwt", 
                  {'version': session['version'], 'country': session['country'], 'doctype': cfgservice.pid_doctype, 'device_publickey': session['device_publickey'], 'data': pdata1}).json()
    if not r1['error_code'] == 0:
        return redirect_getpid(session['version'], session['returnURL'], r1['error_code'], [])
 
    # mdoc from urlsafe_b64encode to b64encode
    mdoc = base64.b64encode(base64.urlsafe_b64decode(r['mdoc']))

    sd_jwt=r1['sd-jwt']

    if session['version'] == "0.1": # result is not ciphered
        return redirect_getpid(session['version'], session['returnURL'], 0, [('mdoc', base64.urlsafe_b64encode(mdoc).decode('utf-8')), ('nonce', ""), ('authTag', ""), ('ciphertextPubKey', ""), ('sd_jwt', sd_jwt)])


    #cipher mdoc
    encryptedMsg = eccEnc(base64.urlsafe_b64decode(session['certificate']), mdoc.decode())
    ciphertext = base64.urlsafe_b64encode(encryptedMsg[0]).decode('utf-8')
    nonce = base64.urlsafe_b64encode(encryptedMsg[1]).decode('utf-8')
    authTag = base64.urlsafe_b64encode(encryptedMsg[2]).decode('utf-8')
    pub64 = base64.urlsafe_b64encode(pubkeyDER(encryptedMsg[3].x, encryptedMsg[3].y)).decode("utf-8")

    return redirect_getpid(session['version'], session['returnURL'], 0, [('mdoc', ciphertext), ('nonce', nonce), ('authTag', authTag), ('ciphertextPubKey', pub64), ('sd_jwt', sd_jwt)])

