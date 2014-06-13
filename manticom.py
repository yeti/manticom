# Manticore Communication
# Copyright (C) 2013, Richard Fung at Yeti LLC
# 
# This script produces nicely formatted RestKit 0.20 mapping based on a JSON schema
# which I haven't documented yet.
#
# URL Meta:
#
# apikey-auth
#
# Data type meta:
#
# optional,
# primarykey or primary
#
# Assumptions:
#
# no endpoint URL can be named nil

import sys
import json
from pprint import pprint, pformat
import StringIO
import os
import logging
from datetime import date
import string
import re

DEFAULT_RESPONSE_CODES = {
    "200+"    :  "successCodes",
    "300+"    :  "redirectCodes",
    "400+"    :  "failCodes",
    "500+"    :  "serverFailCodes"
}

CORE_DATA_TYPES = {
    "date"      : "NSDateAttributeType",            
    "datetime"  : "NSDateAttributeType",            # match data type to Python Django         
    "int"       : "NSInteger32AttributeType",       # C/C++
    "integer"   : "NSInteger32AttributeType",       # sqlite
    "integer16" : "NSInteger16AttributeType",
    "integer32" : "NSInteger32AttributeType",
    "integer64" : "NSInteger64AttributeType",
    "decimal"   : "NSDecimalAttributeType",
    "double"    : "NSDoubleAttributeType",
    "real"      : "NSDoubleAttributeType",          # sqlite
    "float"     : "NSFloatAttributeType",
    "string"    : "NSStringAttributeType",
    "text"      : "NSStringAttributeType",          # sqlite
    "boolean"   : "NSBooleanAttributeType"
}

NS_DATA_TYPES = {
    "date"       : "NSDate",
    "datetime"   : "NSDate", # match data type to Python Django
    "int"        : "NSNumber",
    "integer"    : "NSNumber",
    "integer16"  : "NSNumber",
    "integer32"  : "NSNumber",
    "integer64"  : "NSNumber",
    "decimal"    : "NSNumber",
    "double"     : "NSNumber",
    "real"       : "NSNumber",
    "float"      : "NSNumber",
    "string"     : "NSString",
    "text"       : "NSString",
    "boolean"    : "NSNumber"
}

force_overwrite = False

logging.basicConfig(level=logging.INFO)

def set_subtraction(original_dict, keys_to_remove):
    """
    Removes all keys in keys_to_remove from original_dict and returns a new dictionary with the 
    remaining keys. The original dictionary is unaffected.
    """
    new_dict = original_dict.copy()
    for k in keys_to_remove:
        if k in new_dict:
            new_dict.pop(k)

    return new_dict

def make_suffix(input):
    """
    input some string such as:
        silicon_valley_intelligence
    and the output produces:
        svi
    """
    output = ''.join([s[0:1] for s in re.findall(r"[a-zA-Z0-9']+", input)])
    return output


def check_schema(schema):
    """
    Ensure that the schema is valid for parsing
    """
    status = True
    if not ("urls" in schema and "objects" in schema):
        logging.error("Schema requires two root nodes `urls` and `objects`")
        status = False

    if not isinstance(schema["urls"], list):
        logging.error("Schema requires `urls` as a list")
        status = False
    else:
        for s in schema["urls"]:
            if not ("url" in s or "keyPath" in s):
                logging.warning("Each url definition requires either a `url` or `keyPath`")
                status = False

            if "url" in s:
                if s["url"] == "nil":
                    logging.warning("No url can be named `nil`")

            if not "keyPath" in s:
                d = set_subtraction(s, ["url", "keyPath", "doc", "#meta", "post", "get", "post", "patch", "delete"])

                if len(d) > 0:
                    logging.warning("Don't understand: ")
                    logging.warning(pprint(d.keys()))
                    status = False

    if not isinstance(schema["objects"], list):
        logging.error("Schema requires `objects` as a list")
        status = False
    else:
        for s in schema["objects"]:
            if not isinstance(s, dict):
                logging.error("Every entry in `objects` must be a dictionary")
            else:
                if len(s.keys()) != 1:
                    logging.error("Every object entry in `objects` must contain a single key")
                else:
                    if s.keys()[0][0:1]  != "$":
                        logging.warning("Every object entry in `objects` must begin with a prefix $ for an object name %s " % s.keys()[0])


    return status

def titlecase(name):
    """
    Uppercases the first letter
    """
    return "%s%s" % (name[0:1].upper(), name[1:])

def anti_titlecase(name):
    """
    Lowercases the first letter
    """
    return "%s%s" % (name[0:1].lower(), name[1:]) 

def camel_to_underscore(name):
    """
    convert CamelCase classes to URL-style underscore_name_stuff
    """
    # http://stackoverflow.com/questions/1175208/elegant-python-function-to-convert-camelcase-to-camel-case
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def underscore_to_camel(input):
    """
    converts underscore-style URLs to camel case without the backslash
    """
    output = input.replace("/","_") # remove URL characters in the process
    output = output.replace(":","") # remove the variable notation for RestKit/Ruby
    output = ''.join([titlecase(x) for x in output.split("_")])
    return output

# state is used to determine if capitalize the first 
# default to False per loop
def first_other(first, other, state):
    if state:
        return other
    else:
        return first

def fix_url_path(path):
    """
    remove any prefix / and add suffix /
    """
    if path[0:1] == "/":
        path = path[1:]
    if path[-1:] != "/":
        path = path + "/"

    return path

# change special Cocoa variable names to something else
def safety_name(name):
    if name == "id":
        # not allowed to use _id because underscore not allowed by Core Data modelling tool
        # not allowed to use objectID because it clashes with Core Data internal variable name
        return "theID"
    # http://stackoverflow.com/questions/6327448/semantic-issue-propertys-synthesized-getter-follows-cocoa-naming-convention-fo
    elif name.startswith("new"):
        return "the" + titlecase(name[len("new"):])
    elif name.startswith("alloc"):
        return "loc" + titlecase(name[len("alloc"):])
    elif name.startswith("copy"):
        return "cpy" + titlecase(name[len("copy"):])
    elif name.startswith("mutableCopy"):
        return "mcpy" + titlecase(name[len("mutableCopy"):])
    else:
        return name

def parameter_name(name, state): 
    if name == "id": # id should be especially guarded
        return first_other("Id", "theId", state)
    else:
        return first_other(underscore_to_camel(name), anti_titlecase(underscore_to_camel(name)), state)


def find_key_in_array_of_dict(key, value, arr):
    '''Given a dictionary in the format 
       [{ 
               "key" : "value",
               "k2" : "k2v",
                "k3" : "k3v"
          },
          {
              "a1" : "a1v",
              "a2": "a2v",
              "a3": "a3v"
          }
      ]
      it will extract the object with "key" : "value" in the object
    '''

    for obj in arr:
        if obj[key] == value:
            return obj
    return None

def print_object_response_mapping(outfile, var_name, class_name, attrs, subclasses, is_cached):
    if is_cached:
        outfile.write('RKEntityMapping* %sResponseMapping = [RKEntityMapping mappingForEntityForName:@"%s" inManagedObjectStore:managedObjectStore];\n' % (var_name, class_name))
    else:
        outfile.write('RKObjectMapping* %sResponseMapping = [RKObjectMapping mappingForClass:[%s class]];\n' % (var_name, class_name))
    
    if len(attrs) > 0:
        outfile.write('[%sResponseMapping addAttributeMappingsFromDictionary:@{\n' % var_name)
        first_time = True
        for (a, ns, cd, is_primary, is_optional) in attrs:
            if not first_time:
                outfile.write(",\n")
            outfile.write('                                               @"%s":@"%s"' % (a,safety_name(a)))
            first_time = False
        outfile.write('}];\n')

    
    primary_a = []
    for (a, ns, cd, is_primary, is_optional) in attrs:
        if is_primary:
            primary_a.append(a)
    if len(primary_a) > 0:
        if not is_cached:
            outfile.write("// ")
        outfile.write('%sResponseMapping.identificationAttributes = @[%s];\n' % (var_name, ','.join([ '@"%s"' % safety_name(some_a) for some_a in primary_a ])))

    for (v, d, is_array) in subclasses:
        outfile.write('[%sResponseMapping addPropertyMapping:[RKRelationshipMapping relationshipMappingFromKeyPath:@"%s" toKeyPath:@"%s" withMapping:%sResponseMapping]];\n' % (var_name, v, v, d))

    outfile.write('\n')


def print_object_request_mapping(outfile, var_name, class_name, attrs, subclasses, is_cached):
    outfile.write('RKObjectMapping* %sRequestMapping = [RKObjectMapping requestMapping];\n' % var_name)
    
    if len(attrs) > 0:
        outfile.write('[%sRequestMapping addAttributeMappingsFromDictionary:@{\n' % var_name)
        first_time = True
        for (a, ns, cd, is_primary, is_optional) in attrs:
            if not first_time:
                outfile.write(",\n")
            outfile.write('                                               @"%s":@"%s"' % (safety_name(a),a))
            first_time = False
        outfile.write('}];\n')

    for (v,d,is_array) in subclasses:
        outfile.write('[%sRequestMapping addPropertyMapping:[RKRelationshipMapping relationshipMappingFromKeyPath:@"%s" toKeyPath:@"%s" withMapping:%sRequestMapping]];\n' % (var_name, v, v, d))

    outfile.write('\n')

# read a template file and replace dict keys with their assigned values
# then return the contents of that file
def replace_from_template(template, dict):
    f = open(template, "r")
    contents = f.read()
    for (key, value) in dict.items():
        contents = string.replace(contents, "{{ %s }}" % key, str(value))

    f.close()

    return contents

def get_project_name_from_dir():
    full_dir = os.getcwd()
    dir_parts = full_dir.split("/")
    return dir_parts[-1]


def create_object_files(parent_dir, class_name, attrs, subclasses, is_cached):
    base_object = "NSManagedObject" if is_cached else "NSObject"
    statement = "@dynamic" if is_cached else "@synthesize"

    # default out file is to write to memory
    header_out = None
    body_out = None    

    filename = titlecase(class_name)
    current_files = []

    if os.path.isfile(parent_dir + filename + ".h"):
       if not force_overwrite:
           logging.info("Skipping %s.h..." % filename)
           header_out = open(os.devnull, 'w')
       else:
           logging.info("Overwriting %s.h..." % filename)
           header_out = open(parent_dir + filename + ".h", "w")
    
    else:
        header_out = open(parent_dir + filename + ".h", "w")
        logging.info("Adding file %s.h..." % filename)

    current_files.append(filename + ".h")

    if os.path.isfile(parent_dir + filename + ".m"):
        if not force_overwrite:
            logging.info("Skipping %s.m..." % filename)
            body_out = open(os.devnull, 'w')
        else:
            logging.info("Overwriting %s.m..." % filename)
            body_out = open(parent_dir + filename + ".m", "w")
    else:
        body_out = open(parent_dir + filename + ".m", "w")
        logging.info("Adding file %s.m..." % filename)

    current_files.append(filename + ".m")

    template_dir = os.path.dirname(os.path.realpath(__file__)) + "/"
    template_file = "manticom.h.template"

    # write the header

    # define variable names to replace in the template file
    # if variable names are in the template and not listed here, they won't be replaced
    dict = {"viewName" : class_name,
            "projectName" : get_project_name_from_dir(),
            "date" : date.today().isoformat(),
            "year" : date.today().year,
            "extension" : "h" }

    header_out.write(replace_from_template(template_dir + template_file, dict))
    header_out.write("#import <Foundation/Foundation.h>\n")
    for (variable, t, is_array) in subclasses:
        header_out.write('#import "%s.h"\n' % titlecase(t))
    header_out.write("\n\n")
    header_out.write("@interface %s : %s\n" % ( titlecase(class_name), base_object))
    header_out.write("\n")
    for (a, ns, cd, is_primary, is_optional) in attrs:
        header_out.write("@property(nonatomic, retain) %s* %s;\n" % (ns, safety_name(a)))
    for (variable, t, is_array) in subclasses:
        if is_array:
            header_out.write("@property(nonatomic, retain) %s* %s; // NSArray containing %s\n" % ("NSArray", safety_name(variable), titlecase(t)))
        else:
            header_out.write("@property(nonatomic, retain) %s* %s;\n" % (titlecase(t), safety_name(variable)))
    header_out.write("\n")
    header_out.write("@end\n")
    header_out.close()

    # write the body

    dict = {"viewName" : class_name,
        "projectName" : get_project_name_from_dir(),
        "date" : date.today().isoformat(),
        "year" : date.today().year,
        "extension" : "m" }

    body_out.write(replace_from_template(template_dir + template_file, dict))
    body_out.write('#import "%s.h"\n' % filename)
    body_out.write("\n\n")
    body_out.write("@implementation %s\n" % class_name)
    body_out.write("\n")
    for (a, ns, cd, is_primary, is_optional) in attrs:
        body_out.write("%s %s;\n" % (statement, safety_name(a)))
    for (variable, t, is_array) in subclasses:
        body_out.write("%s %s;\n" % (statement, safety_name(variable)))
    body_out.write("\n@end\n")
    body_out.close()

    return current_files

# Input schema:
# {
#   "#meta":"cached",
#   "key1" :"integer,optional",
#   "key2":"string,primary",
#   "key3":"integer",
#   "key4":"$someObject",
#   "key5":"array,$someObject"
# }

def parse_object_mapping(var_name, obj, completed_objects):
    class_name = titlecase(var_name)
    attrs = []
    subclasses = []
    
    obj = obj.copy()

    is_cached = False
    if "#meta" in obj:
        tags = obj["#meta"].split(",")
        is_cached = "cached" in tags
        tags.remove("cached")

        if len(tags) > 0:
            logging.warning("Don't understand the meta tag %s for variable %s" % (pformat(tags), var_name))

        obj.pop("#meta")

    for variable in obj.keys():
        attr_type = obj[variable].split(",")
        is_optional = False
        is_primary = False
        is_array = False
        if "optional" in attr_type:
            attr_type.remove("optional")
            is_optional = True

        # support either primarykey or primary attribute
        if "primarykey" in attr_type:
            attr_type.remove("primarykey")
            is_primary = True
        elif "primary" in attr_type:
            attr_type.remove("primary")
            is_primary = True

        if "array" in attr_type:
            attr_type.remove("array")
            is_array = True

        if len(attr_type) != 1:
            logging.warning("Don't understand attributes: ")
            logging.warning(pprint(attr_type))

        data_type = attr_type[0]
        if data_type[0:1] != "$":
            ns_string = NS_DATA_TYPES[data_type]
            cd_string = CORE_DATA_TYPES[data_type]

            if is_array:
                logging.warning("Primitive data type `%s` on `%s` with the `array` attribute is untested" % (variable, var_name))
                ns_string = "NSArray"
                cd_string = "NSUndefinedAttributeType"
            
            attrs.append((variable, ns_string, cd_string, is_primary, is_optional))
        else:
            if not data_type in completed_objects:
                logging.error("Incomplete reference %s to %s " % (variable, data_type))

            if is_primary:
                logging.error("Object data type `%s` on `%s` cannot have the `primary` attribute " % (variable, var_name))

            if is_optional:
                logging.error("Object data type `%s` on `%s` cannot have the `optional` attribute " % (variable, var_name))

            subclasses.append((variable, data_type[1:], is_array))

    return { "var_name" : var_name,
             "class_name" : class_name,
             "attrs" : attrs,
             "subclasses" : subclasses,
             "is_cached" : is_cached}

def print_auth_type(outfile, auth_type):
    closing_line = "} else { \n[sharedMgr.HTTPClient clearAuthorizationHeader];\n}\n"
    if "basic" in auth_type:
        if "optional" in auth_type:
            outfile.write("if ([AppModel sharedModel].user && [AppModel sharedModel].user.username && [AppModel sharedModel].password) { \n")
        outfile.write("[sharedMgr.HTTPClient setAuthorizationHeaderWithUsername:[AppModel sharedModel].user.username password:[AppModel sharedModel].password];\n")
        if "optional" in auth_type:
            outfile.write(closing_line)
    elif "oauth" in auth_type:
        if "optional" in auth_type:
            outfile.write("if ([AppModel sharedModel].apikey]) {\n")
        outfile.write("[sharedMgr.HTTPClient setAuthorizationHeaderWithToken:[AppModel sharedModel].apikey];\n")
        if "optional" in auth_type:
            outfile.write(closing_line)
    elif "tastypie" in auth_type:
        if "optional" in auth_type:
            outfile.write("if ([AppModel sharedModel].user && [AppModel sharedModel].user.username && [AppModel sharedModel].apikey) { \n")
        outfile.write("[sharedMgr.HTTPClient setAuthorizationHeaderWithTastyPieUsername:[AppModel sharedModel].user.username andToken:[AppModel sharedModel].apikey];\n")
        if "optional" in auth_type:
            outfile.write(closing_line)
    else:
        outfile.write('[sharedMgr.HTTPClient clearAuthorizationHeader];\n')

def print_parameter_dict(outfile, param):
    if len(param):
        outfile.write("NSMutableDictionary* paramDict = [NSMutableDictionary dictionaryWithCapacity:%d];\n" % len(param))
        for (var, ns, cd, is_primary, is_optional) in param:
            outfile.write("if (%s) {\n" % safety_name(var))
            outfile.write('[paramDict setObject:%s forKey:@"%s"];\n' % (safety_name(var), var))
            outfile.write("}\n")

        return "paramDict"
    else:
        return "nil"

# finds and returns the first primary key for a resource, assume only one primary key is allowed
def get_primary_key_from_params(attrs):
    if not attrs:
        return (None, None, None)

    for (var, ns, cd, is_primary, is_optional) in attrs:
        if is_primary:
            return (var, ns, cd)
    return (None, None, None)

# adds the @"" to a url if primary key is created, so the variable name is returned
# primary_payload = get_primary_key_from_params(...)
# method is used for debugging assistance only
def get_decorated_url_with_primary_key(outfile, url, primary_payload, method = ""):
    (primary_key, ns, cd) = primary_payload # unpack the output from get_primary_key_from_params()
    if primary_key:
        if url.find(":%s" % primary_key) == -1 and method != "delete":
            logging.warn("URL `%s` should contain the primary key `:%s` for proper RestKit mapping" % (url, primary_key))
        url = url.replace(":%s" % primary_key, "") # automatically remove `:primary_key` from the URL
        url = url.rstrip('/') # and extra trailing backslashes
        outfile.write('NSString* fullUrl = [NSString stringWithFormat:@"%s/%s/", %s];\n' % (url, "%@", safety_name(primary_key)))
        return "fullUrl"
    else:
        if url != "nil":
            url = '@"%s"' % url

        if url.find(":") != -1:
            logging.warn("URL %s may refer to a URL parameter without a `prototype`. RestKit mapping will fail." % url)

        return url

# prototype_attrs can be None or an array of attributes
def print_get_method(url, outfile, var_name, class_name, prototype_attrs, param, is_header, auth_type):
    outfile.write("-(void) getAll%sWith" % underscore_to_camel(url))

    # print primary key, no other attributes are output
    toggle_state = False
    (primary_key, ns, cd) = get_primary_key_from_params(prototype_attrs)
    if primary_key:
        outfile.write("%s:(%s*)%s " % (parameter_name(primary_key, toggle_state), ns, safety_name(primary_key)))
        toggle_state = True


    for (var, ns, cd, is_primary, is_optional) in param:
        outfile.write("%s:(%s*)%s " % (parameter_name(var, toggle_state), ns, safety_name(var)))
        toggle_state = True

    if not toggle_state:
        outfile.write("Success")
    else:
        outfile.write("success")

    outfile.write(":(void (^)(RKObjectRequestOperation *operation, RKMappingResult *mappingResult))success failure:(void (^)(RKObjectRequestOperation *operation, NSError *error))failure")
    if is_header:
        outfile.write(";\n\n")
    else:
        outfile.write(" {\n")
        outfile.write("RKObjectManager* sharedMgr = [RKObjectManager sharedManager];\n")
        param_dict = print_parameter_dict(outfile, param)
        print_auth_type(outfile, auth_type)

        url = get_decorated_url_with_primary_key(outfile, url, get_primary_key_from_params(prototype_attrs), "get")
        
        outfile.write('[sharedMgr getObjectsAtPath:%s parameters:%s success:success failure:failure];\n' % (url, param_dict))
        outfile.write('}\n\n')

# attrs are used to identify the primary key, they aren't printed
# all parameters are printed
def print_delete_method(url, outfile, prototype_attrs, param, is_header, auth_type):
    outfile.write("-(void) delete%sWith" % underscore_to_camel(url))

    # print primary key, no other attributes are output
    toggle_state = False
    (primary_key, ns, cd) = get_primary_key_from_params(prototype_attrs)
    if primary_key:
        outfile.write("%s:(%s*)%s " % (parameter_name(primary_key, toggle_state), ns, safety_name(primary_key)))
        toggle_state = True
    else:
        # delete always has to print out a primary key
        primary_key = "PRIMARY_KEY"
        logging.warn("No PRIMARY_KEY specified for delete `%s`" % url)

    # print all parameters
    for (var, ns, cd, is_primary, is_optional) in param:
        outfile.write("%s:(%s*)%s " % (parameter_name(var, toggle_state), ns, safety_name(var)))
        toggle_state = True


    if not toggle_state:
        outfile.write("Success")
    else:
        outfile.write("success")

    outfile.write(":(void (^)(RKObjectRequestOperation *operation, RKMappingResult *mappingResult))success failure:(void (^)(RKObjectRequestOperation *operation, NSError *error))failure")
    if is_header:
        outfile.write(";\n\n")
    else:
        outfile.write(" {\n")
        outfile.write("RKObjectManager* sharedMgr = [RKObjectManager sharedManager];\n")

        param_dict = print_parameter_dict(outfile, param)

        print_auth_type(outfile, auth_type)

        url = get_decorated_url_with_primary_key(outfile, url, get_primary_key_from_params(prototype_attrs), "delete")

        outfile.write('[sharedMgr deleteObject:nil path:%s parameters:%s success:success failure:failure];\n' % (url, param_dict))
        outfile.write('}\n\n')    


def print_access_method(method, url, var_name, class_name, attrs, prototype_attrs, subclasses, param, is_header, outfile, auth_type):
    toggle_state = False
    outfile.write("-(void) %s%sWith" % (method, underscore_to_camel(url)))

    # choose between prototype primary key or request primary key, whichever is provided
    (primary_key, ns, cd) = get_primary_key_from_params(prototype_attrs)
    if not primary_key:
        (primary_key, ns, cd) = get_primary_key_from_params(attrs)

    # write the primary key first
    if primary_key:
        outfile.write("%s:(%s*)%s " % (parameter_name(primary_key, toggle_state), ns, safety_name(primary_key)))
        toggle_state = True

    # write other attributes
    for (var, ns, cd, is_primary, is_optional) in attrs:
        if not is_primary:
            outfile.write("%s:(%s*)%s " % (parameter_name(var, toggle_state), ns, safety_name(var)))
            toggle_state = True    

    # write classes
    for (var, ns, is_array) in subclasses:
        outfile.write("%s:(%s*)%s " % (parameter_name(var, toggle_state), titlecase(ns), safety_name(var)))
        toggle_state = True

    # write additional parameters
    for (var, ns, cd, is_primary, is_optional) in param:
            outfile.write("%s:(%s*)%s " % (parameter_name(var, toggle_state), ns, safety_name(var)))
            toggle_state = True

    if not toggle_state:
        outfile.write("Success")
    else:
        outfile.write("success")
        
    outfile.write(":(void (^)(RKObjectRequestOperation *operation, RKMappingResult *mappingResult))success failure:(void (^)(RKObjectRequestOperation *operation, NSError *error))failure")

    if is_header:
        outfile.write(";\n\n")
    else:
        outfile.write(" {\n")
        outfile.write("RKObjectManager* sharedMgr = [RKObjectManager sharedManager];\n")
        outfile.write("%s* obj = [%s new];\n" % (class_name, class_name))
        for (var, ns, cd, is_primary, is_optional) in attrs:
            outfile.write("obj.%s = %s;\n" % (safety_name(var), safety_name(var)))
        for (var, ns, is_array) in subclasses:
            outfile.write("obj.%s = %s;\n" % (safety_name(var), safety_name(var)))
        outfile.write("\n")

        param_dict = print_parameter_dict(outfile, param)

        print_auth_type(outfile, auth_type)

        # choose between prototype primary key or request primary key, whichever is provided
        (primary_key, ns, cd) = get_primary_key_from_params(prototype_attrs)
        if not primary_key:
            (primary_key, ns, cd) = get_primary_key_from_params(attrs)

        url = get_decorated_url_with_primary_key(outfile, url, (primary_key, ns, cd), method)

        outfile.write("[sharedMgr %sObject:obj path:%s parameters:%s success:^(RKObjectRequestOperation *operation, RKMappingResult *mappingResult) {\n" % (method, url, param_dict))
        outfile.write("    success(operation, mappingResult); } \n")
        outfile.write("    failure:failure];\n}\n\n")

# # This method is useful for debugging only. We don't know the object graph of requests and responses until we have fulled parsed the URL mappings.
# def parse_objects_as_responses(schema, outfile):
#     completed_objects = [] # object names with the $ prefix

#     for key in schema.keys():
#         obj = schema[key]

#         if key[0:1] != "$":
#             print "Not an object definition"
#             continue

#         var_name = key[1:]
#         parse_object_mapping(var_name, obj, print_object_response_mapping, completed_objects, outfile)

#         completed_objects.append(key)

# Input schema example (objects):
    # "$meta":{
    #     "limit" :"integer",
    #     "next":"string",
    #     "offset":"integer",
    #     "previous":"string",
    #     "total_count":"integer"
    # },
    # "$user": {
    #     "username": "string,primarykey",
    #     "email": "string"
    # }
# TODO : match the input and output schemas rf
# Output schema example (expanded objects):
# [
# {'class_name': u'ChangePasswordRequest', 
#   'is_cached': False,
#   'var_name': u'changePasswordRequest',
#   'subclasses': [(u'related_tags', u'tag',True), (u'user_profile', u'userProfileResponse',False)], 
#   'attrs': [(u'new_password', 'NSString', 'NSStringAttributeType', False, False),
#             (u'old_password', 'NSString', 'NSStringAttributeType', False, False)]
# },
# {'class_name': u'SignupRequest', 
#    'is_cached': False,
#    'var_name': u'signupRequest',
#   ... 
# }
# ]
def parse_all_objects(schema):
    completed_objects = [] # object names with the $ prefix
    request_objects = []

    for el in schema:
        if len(el.keys()) != 1:
            logging.error("Mapping a key in `objects` should contain a single object only")

        for key in el.keys():
            obj = el[key]

            if key[0:1] != "$":
                logging.error("Not an object definition in the format $defName: %s" % key)
                continue

            var_name = key[1:]
            d = parse_object_mapping(var_name, obj, completed_objects)
            request_objects.append(d)
            completed_objects.append(key)

    return request_objects


def parse_objects_from_list(expanded_objects, list):
    request_objects = []

    for d in expanded_objects:
        if d["var_name"] in list:
            request_objects.append(d)

    return request_objects

# Input schema:
# [
# {'class_name': u'ChangePasswordRequest', 
#   'is_cached': False,
#   'var_name': u'changePasswordRequest',
#   'subclasses': [], 
#   'attrs': [(u'new_password', 'NSString', 'NSStringAttributeType', False, False),
#             (u'old_password', 'NSString', 'NSStringAttributeType', False, False)]
# },
# {'class_name': u'SignupRequest', 
#    'is_cached': False,
#    'var_name': u'signupRequest',
#   ... 
# }
# ]
def print_request_mapping(schema, outfile):
    for d in schema:
        print_object_request_mapping(outfile, d['var_name'], d['class_name'], d['attrs'], d['subclasses'],d['is_cached'])

def print_response_mapping(schema, outfile):
    for d in schema:
        print_object_response_mapping(outfile, d['var_name'], d['class_name'], d['attrs'], d['subclasses'],d['is_cached'])


# HERE IT IS
        
def create_object_files_at_project_dir_from_internal_schema(project_dir, schema):
    objs_dir = project_dir + "/Objects/"

    if not os.path.exists(objs_dir):
        os.makedirs(objs_dir)

    old_files = os.listdir(objs_dir)
    current_files = []

    for d in schema:
        current_files += create_object_files(objs_dir, d['class_name'], d['attrs'], d['subclasses'], d['is_cached'])

    for file_name in set(old_files).difference(set(current_files)):
        os.remove(objs_dir + file_name)
        logging.info("Deleted: %s" % file_name)

# def parse_response_objects_from_list(schema, list, outfile):
#     completed_objects = [] # object names with the $ prefix

#     for key in schema.keys():
#         obj = schema[key]

#         if key[0:1] != "$":
#             logging.error("Not an object definition in the format $defName: %s" % key)
#             continue

#         var_name = key[1:]
#         if var_name in list:
#             d = parse_object_mapping(var_name, obj, completed_objects, outfile)
#             # print_object_response_mapping(outfile, d['var_name'], d['class_name'], d['attrs'], d['subclasses'], d['is_cached'])
#             # create_object_files(d['class_name'], d['attrs'], d['subclasses'], d['is_cached'])
#             completed_objects.append(key)


# Assumptions:
# Payload:
#   "get", "patch", "post", "delete", "options", "put", or "head"
# Returns:
#   The RKRequestMethod matching the function we are mapping to

def get_rk_method(method):
    if method == "Get":
        return "RKRequestMethodGET"
    elif method == "Patch":
        return "RKRequestMethodPATCH"
    elif method == "Post":
        return "RKRequestMethodPOST"
    elif method == "Delete":
        return "RKRequestMethodDELETE"
    elif method == "Options":
        return "RKRequestMethodOPTIONS"
    elif method == "Put":
        return "RKRequestMethodPUT"
    elif method == "Head":
        return "RKRequestMethodHEAD"
    else:
        return "RKRequestMethodInvalid"


# Assumptions:
# Payload:
#    "$someObject"
def print_request_url(outfile, url, request, method):
    var_name = request[1:]
    class_name = titlecase(var_name)
    suffix = "_" + make_suffix(url)

    rk_method = get_rk_method(method)

    outfile.write('RKRequestDescriptor* %s_Request%s%s = [RKRequestDescriptor requestDescriptorWithMapping:%sRequestMapping objectClass:[%s class] rootKeyPath:nil method:%s];\n' %
        (var_name, titlecase(method),suffix, var_name, class_name, rk_method))

    return (var_name, "%s_Request%s%s" % (var_name, titlecase(method), suffix))


# Assumptions:
#     predefined values are successCodes, failCodes, serverFailCodes, and continueCodes
# Payload:
#    "$someObject"
# or
#    { "200+" : "$someObject" }
# or 
#    { "400" : "$someErrorObject" }
# or
#    { "200+" : "$someObject",
#      "keyPath" : "objects" }
# Returns:
#   name of the response descriptor
def print_response_url(outfile, url, response, method):
    codes = "successCodes"
    keyPath = "nil"
    var_name = None
    var_name_suffix = method

    rk_method = get_rk_method(method)

    if isinstance(response, dict):
        keys = list(response.keys())
        values = response.values()

        if "keyPath" in keys:
            keyPath = '@"%s"' % response["keyPath"]
            response.pop("keyPath")
            keys.remove("keyPath")

        if len(keys) != 1:
            logging.warning("Don't understand response for url=%s and keypath=%s" % (url, keyPath))

        codes = ""
        if keys[0] in DEFAULT_RESPONSE_CODES:
            codes = DEFAULT_RESPONSE_CODES[keys[0]]
        else:
            code_num = int(keys[0]) # test convert the index number to an integer
            codes = '[NSIndexSet indexSetWithIndex:%s]' % keys[0]
            var_name_suffix = var_name_suffix + keys[0]  

        var_name = response[keys[0]][1:]
    else:
        var_name = response[1:]
    
    second_suffix = "_" + make_suffix(url)

    if url != "nil":
        url = '@"%s"' % url

    outfile.write('RKResponseDescriptor* %s_Response%s%s = [RKResponseDescriptor responseDescriptorWithMapping:%sResponseMapping method:%s pathPattern:%s keyPath:%s statusCodes:%s];\n' %
                (var_name, var_name_suffix, second_suffix, var_name, rk_method, url, keyPath, codes))

    return (var_name, "%s_Response%s%s" % (var_name, var_name_suffix, second_suffix))


# Payload:
#   {"url" : "some_url/",
#    "get" : { <response> },
#    "post" : { <response> },
#    "put" : { <response> },
#     ...}
# or
#   {<response>}
def parse_urls(schema, outfile):
    requests = []
    responses = []
    root_objects = []

    request_mappings = []
    response_mappings = []

    # write out responses associated to an url

    for obj in schema:
        url = "nil"
        if "url" in obj:
            original_url = fix_url_path(obj["url"])

            first_time = True

            for method in ["get", "post", "put", "patch", "delete"]:
                if method in obj:
                    if "response" in obj[method]:
                        if first_time:
                            outfile.write("\n// Mapping for %s\n\n" % original_url)
                            first_time = False

                        (var_name, response_name) = print_response_url(outfile, original_url, obj[method]["response"], titlecase(method))
                        responses.append(response_name)
                        response_mappings.append(var_name)

                    if "request" in obj[method]:
                        if first_time:
                            outfile.write("\n// Mapping for %s\n\n" % original_url)
                            first_time = False

                        (var_name, request_name) = print_request_url(outfile, original_url, obj[method]["request"], titlecase(method))
                        requests.append(request_name)
                        request_mappings.append(var_name)



        else:
            root_objects.append(obj)

    # write out root responses thereafter

    if len(root_objects):
        outfile.write("\n// Responses applied to any URL\n\n")

    for obj in root_objects:
        (var_name, response_name) = print_response_url(outfile, url, obj, "")
        responses.append(response_name)
        response_mappings.append(var_name)

    outfile.write('''

// Configure RestKit to handle requests and responses

NSString* strBase = [NSString stringWithFormat:@"%s", BASE_URL, API_URL];
NSURL* url = [NSURL URLWithString:strBase];
RKObjectManager* manager = [RKObjectManager managerWithBaseURL:url];
manager.requestSerializationMIMEType = RKMIMETypeJSON;
manager.managedObjectStore = managedObjectStore;
[manager addRequestDescriptorsFromArray:@[%s]];
[manager addResponseDescriptorsFromArray:@[%s]];\n\n''' % ('%@%@', ", ".join(requests),  ", ".join(responses)))

    # remove duplicates in request and response mappings
    request_mappings = list(set(request_mappings))
    response_mappings = list(set(response_mappings))

    return (request_mappings, response_mappings)



# Input url:
#   {
#        "url" : "some_url/",
#        "get" : { <response> },
#        "post" : { <response> },
#        "put" : { <response> },
#         ...
#   }
# or
#   {
#        <response>
#   }
#
# Input objects (expanded object schema):
# [
# {'class_name': u'ChangePasswordRequest', 
#   'is_cached': False,
#   'var_name': u'changePasswordRequest',
#   'subclasses': [], 
#   'attrs': [(u'new_password', 'NSString', 'NSStringAttributeType', False, False),
#             (u'old_password', 'NSString', 'NSStringAttributeType', False, False)]
# },
# {'class_name': u'SignupRequest', 
#    'is_cached': False,
#    'var_name': u'signupRequest',
#   ... 
# }
# ]
def print_methods_from_urls(urls, objects, is_header, outfile):
    # write out responses associated to an url

    for obj in urls:
        if "url" in obj:
            url = fix_url_path(obj["url"])

            outfile.write("\n// Operations for `%s`\n" % url)

            if is_header and "doc" in obj:
                if len(obj["doc"]) > 0:
                    outfile.write("// %s\n" % obj["doc"])
            outfile.write("\n")

            for method in ["post", "put", "patch", "delete", "get"]:
                if method in obj:
                    if is_header and "doc" in obj[method]:
                        if len(obj[method]["doc"]) > 0:
                            outfile.write("// %s\n" % obj[method]["doc"])

                    # extract the meta tag and handle the instruction
                    auth_type = ""
                    if "#meta" in obj[method]:
                        auth_type = obj[method]["#meta"].split(",")

                        # convert long form names to short form
                        if "basicauth" in auth_type:
                            auth_type.append("basic")
                            auth_type.remove("basicauth")
                        elif "tastypieauth" in auth_type:
                            auth_type.append("tastypie")
                            auth_type.remove("tastypieauth")

                    param = []
                    if "parameters" in obj[method]:
                        d = find_key_in_array_of_dict("var_name", obj[method]["parameters"][1:], objects)
                        param = d['attrs']
                        # only use primitive parameters for now, we don't waste time with nested object parameters
                        if len(d['subclasses']) > 0:
                            logging.error("Non-primitive parameters are presently disallowed for %s `%s`" % (method, url))

                    prototype_attrs = None
                    if "prototype" in obj[method]:
                        (v2, r2) = print_response_url(StringIO.StringIO(), url, obj[method]["prototype"], titlecase(method))
                        class_name = titlecase(v2)
                        d = find_key_in_array_of_dict("var_name", v2, objects)
                        prototype_attrs = d["attrs"]

                    if method == "get":
                        if "response" in obj[method]:
                            (var_name, response_name) = print_response_url(StringIO.StringIO(), url, obj[method]["response"], titlecase(method))
                            class_name = titlecase(var_name)

                            if "request" in obj[method]:
                                logging.error("Cannot make a %s `%s` request for the url `%s`" % (method, class_name, url))

                            print_get_method(url, outfile, var_name, class_name, prototype_attrs, param, is_header, auth_type)
                        else:
                            logging.error("Cannot map a %s `%s` request without a response definition" % (method,url))

                    elif method == "delete":
                        # use either the request or response object to sniff out the primary key
                        if prototype_attrs:
                            print_delete_method(url, outfile, prototype_attrs, param, is_header, auth_type)
                        else:
                            logging.error("Canno map %s `%s` without a prototype " % (method,url))                        
                    else:

                        if "request" in obj[method]:
                            (var_name, request_name) = print_request_url(StringIO.StringIO(), url, obj[method]["request"], titlecase(method))
                            class_name = titlecase(var_name)
                            d = find_key_in_array_of_dict("var_name", var_name, objects)
                            print_access_method(method, url, var_name, class_name, d['attrs'], prototype_attrs, d['subclasses'], param, is_header, outfile, auth_type)
                        else:
                            logging.error("Cannot make a %s `%s` without a request definition" % (method, url))


def print_imports(list, outfile):
    for v in list:
        outfile.write('#import "%s.h"\n' % titlecase(v))


# builds an object list that searches for other referenced objects
def build_object_list(mapping_names, expanded_object_schema):
    new_list = []
    referenced_names = []

    # print "Build object list %s" % pformat(mapping_names)

    for d in expanded_object_schema:
        if d["var_name"] in mapping_names:
            submapping = [obj_name for (var_name, obj_name, is_array) in d["subclasses"]]
            if len(submapping):
                new_list.extend(build_object_list(submapping, expanded_object_schema))
            new_list.append(d["var_name"])
            referenced_names.append(d["var_name"])

    dif_set = set(mapping_names).difference(referenced_names)

    if len(dif_set) > 0:
        logging.error("Objects were referenced but not defined: %s" % pformat(dif_set))

    return list(set(new_list))
#
# main method ==================================================================================================================================
#

def main_script(filename):
    f = open(filename, "r")
    schema = json.loads(f.read())
    f.close()

    check_schema(schema)
    #parse_objects_as_responses(schema["objects"], sys.stdout)

    mapping_buffer = StringIO.StringIO()

    #Testing
    project_dir = raw_input("Please enter your project directory\n: ")
    
    models_dir = project_dir + "/Machine/"

    if not os.path.exists(models_dir):
        os.makedirs(models_dir)

    print(models_dir)
    m_buffer = open(models_dir + "MachineDataModel.m", "w")
    h_buffer = open(models_dir + "MachineDataModel.h", "w")

    h_buffer.write('''
//
//  MachineDataModel.h
//
//  Copyright (c) 2014 Yeti LLC. All rights reserved.
//

#import <Foundation/Foundation.h>
#import <RestKit/RestKit.h>

@interface MachineDataModel : NSObject

+ (MachineDataModel*)sharedModel;

+ (BOOL)isDefined: (id) object;

-(void)setupMapping;
                   ''')

    m_buffer.write('''
//
//  MachineDataModel.m
//
//  Copyright (c) 2014 Yeti LLC. All rights reserved.
//

#import "MachineDataModel.h"

#import <RestKit/RestKit.h>
#import <AFNetworking-TastyPie/AFNetworking+ApiKeyAuthentication.h>

#import "AppModel.h"
                   ''')

    # parse and print url mapping buffer
    (request_mappings, response_mappings) = parse_urls(schema["urls"], mapping_buffer)

    # parse object definitions
    expanded_objects = parse_all_objects(schema["objects"])

    # build request and response buffer
    request_mappings = build_object_list(request_mappings, expanded_objects)
    response_mappings = build_object_list(response_mappings, expanded_objects)
    mappings = request_mappings[:]
    mappings.extend(response_mappings)
    mappings = list(set(mappings)) # remove duplicates

    m_buffer.write("\n")
    print_imports(mappings, m_buffer)
    m_buffer.write("\n")
    m_buffer.write('''
@implementation MachineDataModel

// http://www.galloway.me.uk/tutorials/singleton-classes/
+ (MachineDataModel*)sharedModel {
  static MachineDataModel *sharedModel = nil;
  static dispatch_once_t onceToken;
  dispatch_once(&onceToken, ^{
    sharedModel = [[self alloc] init];
  });
  return sharedModel;
}

+(BOOL) isDefined: (id) object {
  return object != nil && object != [NSNull null];
}

  ////////////////////
 //MACHINE MAPPINGS//
////////////////////
#pragma mark -
#pragma mark Machine Mappings
                   ''')

    

    m_buffer.write('''-(void)setupMapping {
NSIndexSet *successCodes = RKStatusCodeIndexSetForClass(RKStatusCodeClassSuccessful);
NSIndexSet *failCodes = RKStatusCodeIndexSetForClass(RKStatusCodeClassClientError);
NSIndexSet *serverFailCodes = RKStatusCodeIndexSetForClass(RKStatusCodeClassServerError);
NSIndexSet *redirectCodes = RKStatusCodeIndexSetForClass(RKStatusCodeClassRedirection);


// managed object manager
NSError* error = nil;
NSManagedObjectModel *managedObjectModel = [NSManagedObjectModel mergedModelFromBundles:nil];
RKManagedObjectStore *managedObjectStore = [[RKManagedObjectStore alloc] initWithManagedObjectModel:managedObjectModel];
BOOL success = RKEnsureDirectoryExistsAtPath(RKApplicationDataDirectory(), &error);
if (! success) {
    RKLogError(@"Failed to create Application Data Directory at path '%@': %@", RKApplicationDataDirectory(), error);
}
NSString *path = [RKApplicationDataDirectory() stringByAppendingPathComponent:DATABASE_FILE];
NSPersistentStore *persistentStore = [managedObjectStore addSQLitePersistentStoreAtPath:path fromSeedDatabaseAtPath:nil withConfiguration:nil options:nil error:&error];
if (! persistentStore) {
    RKLogError(@"Failed adding persistent store at path '%@': %@", path, error);
}
[managedObjectStore createManagedObjectContexts];

// RestKit object mappings

''')

    # parse the original objects schema into an expanded format
    parsed_requests = parse_objects_from_list(expanded_objects, request_mappings)
    parsed_responses = parse_objects_from_list(expanded_objects, response_mappings)

    assert len(parsed_requests) == len(request_mappings)
    assert len(parsed_responses) == len(response_mappings)

    # create objects for all defined objects, only for requests and responses 
    # (parameters are excluded, they are passed individually as arguments)
    # Combine parsed_requests and parsed_responses in single call to make it more apparent
    # which files have been added or deleted

    # need to pass path here.......
    create_object_files_at_project_dir_from_internal_schema(project_dir, parsed_requests + parsed_responses)

    # output mappings for objects that are referenced by requests and responses
    print_request_mapping(parsed_requests, m_buffer)
    print_response_mapping(parsed_responses, m_buffer)

    m_buffer.write(mapping_buffer.getvalue())
    m_buffer.write("}\n\n")

    # print headers
    print_methods_from_urls(schema["urls"], expanded_objects, False, m_buffer)
    m_buffer.write("\n\n")

    # print body definitions for those headers (DataModel.h)
    print_methods_from_urls(schema["urls"], expanded_objects, True, h_buffer)

    h_buffer.write('''
@end
                   ''')
    m_buffer.write('''
@end
                   ''')

    m_buffer.close()
    h_buffer.close()


# supports two formats
# script.py -f filename
# script.py filename
if len(sys.argv) > 3 or len(sys.argv) <= 1:
    print "Usage: " + sys.argv[0] + " <filename>"
    print "       " + sys.argv[0] + " -f <filename>"
    print "   where -f forces existing files to be overwritten"
else:
    i = 1
    if sys.argv[1] == "-f":
        force_overwrite = True
        i = 2
        if len(sys.argv) != 3:
            print "-f force argument without a filename"

    main_script(sys.argv[i])
