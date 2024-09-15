from flask import Blueprint, request, current_app
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import PrimaryKeyConstraint, UniqueConstraint, Integer, Float, BOOLEAN, Boolean, Enum
from sqlalchemy.sql import text
from sqlalchemy.orm.exc import UnmappedInstanceError
from functools import wraps
import logging
import json

__version__ = '0.9.3'

SQLTYPE_TO_FLASKTYPE = {Integer: 'int', Float: 'float'}
SQLTYPE_TO_SWAGGERTYPE = {Integer: 'integer', Float: 'number', BOOLEAN: 'boolean', Boolean: 'boolean'}


def model_to_dict(obj):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if 'not visible by api' not in str(c.comment)}


def getConstraint(cls):
    constraint = None
    if len([constraint for constraint in cls.__table__.constraints if isinstance(constraint, UniqueConstraint)]) > 0:
        constraint = [constraint for constraint in cls.__table__.constraints if isinstance(constraint, UniqueConstraint)][0]
    if len([constraint for constraint in cls.__table__.constraints if isinstance(constraint, PrimaryKeyConstraint)]) > 0:
        constraint = [constraint for constraint in cls.__table__.constraints if isinstance(constraint, PrimaryKeyConstraint)][0]
    if constraint is None:
        raise "%s does not PrimaryKeyConstraint or UniqueConstraint" % cls.__name__
    return constraint


def unique_endpoint(cls):
    constraint = getConstraint(cls)
    return ("/".join(["<%s:%s>" % (SQLTYPE_TO_FLASKTYPE.get(column.type.__class__, 'string'), column.name) for column in constraint.columns]))


class ItemNotFound(Exception):

    def __init__(self, item):
        super().__init__("Item not found %s" % item)


def requestBody(obj, method):
    content = {"application/json": {"schema": {"type": "object", "properties": {}}}}
    if method == 'POST':
        for c in [c for c in obj.__table__.columns if c.autoincrement is not True and 'not create by api' not in str(c.comment)]:
            content["application/json"]["schema"]["properties"][c.name] = {"type": SQLTYPE_TO_SWAGGERTYPE.get(c.type.__class__, 'string')}
            if c.type.__class__ == Enum:
                content["application/json"]["schema"]["properties"][c.name]["enum"] = [member for member in c]
        return content
    if method in ["PUT", "PATCH"]:
        for c in [c for c in obj.__table__.columns if 'not update by api' not in str(c.comment)]:
            content["application/json"]["schema"]["properties"][c.name] = {"type": SQLTYPE_TO_SWAGGERTYPE.get(c.type.__class__, 'string')}
            if c.type.__class__ == Enum:
                content["application/json"]["schema"]["properties"][c.name]["enum"] = [member for member in c]
        return content
    return None


def responseBody(obj, method):
    content = {"application/json": {"schema": {"type": "object", "properties": {}}}}
    for c in [c for c in obj.__table__.columns if 'not visible by api' not in str(c.comment)]:
        content["application/json"]["schema"]["properties"][c.name] = {"type": SQLTYPE_TO_SWAGGERTYPE.get(c.type.__class__, 'string')}
        if c.type.__class__ == Enum:
            content["application/json"]["schema"]["properties"][c.name]["enum"] = [member for member in c]
    if method == 'ALL':
        obj = content["application/json"]["schema"]
        content = {"application/json": {"schema": {"type": "array", "items": obj}}}
    return content


def error_api(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except UnmappedInstanceError as err:
            return {"code": 400, 'description': 'Item not found, %s' % str(err)}, 400
        except Exception as err:
            return {"code": 400, 'description': str(err)}, 400
    return decorated_view


def multi_decorators(decorators):
    def decorator(f):
        for d in reversed(decorators):
            f = d(f)
        return f
    return decorator


class ApiRest(Blueprint):

    def __init__(self, db, name='apirest', import_name=__name__, url_prefix='/api/v1', *args, **kwargs):
        Blueprint.__init__(self, name, import_name, url_prefix, *args, **kwargs)
        self._db = db
        self._url_prefix = url_prefix

    def add_api(self, cls, method, decorators=[], endpoint=None, serialize=model_to_dict):
        _origin_method = method
        decorators = [error_api,] + decorators
        if method not in ['ALL', 'POST', 'GET', 'DELETE', 'PUT', 'PATCH']:
            raise "%s is not a method value (ALL, POST, GET, DELETE, PUT, PATCH)" % method
        if method == 'ALL':
            method = 'GET'
            parameters = []
            if endpoint is None:
                endpoint = '%s/%ss' % (self._url_prefix, cls.__name__.lower())
            self.add_url_rule(endpoint, 'view_%ss' % endpoint[1:], multi_decorators(decorators)(self._all(cls, serialize)), methods=[method, ])
        elif method == 'POST':
            parameters = []
            if endpoint is None:
                endpoint = '%s/%s' % (self._url_prefix, cls.__name__.lower())
            self.add_url_rule(endpoint, 'post_%s' % endpoint[1:], multi_decorators(decorators)(self._post(cls, serialize)), methods=[method, ])
        elif method == 'GET':
            parameters = getConstraint(cls)
            if endpoint is None:
                endpoint = '%s/%s/%s' % (self._url_prefix, cls.__name__.lower(), unique_endpoint(cls))
            self.add_url_rule(endpoint, 'get_%s' % endpoint[1:], multi_decorators(decorators)(self._get(cls, serialize)), methods=[method, ])
        elif method == 'DELETE':
            parameters = getConstraint(cls)
            if endpoint is None:
                endpoint = '%s/%s/%s' % (self._url_prefix, cls.__name__.lower(), unique_endpoint(cls))
            self.add_url_rule(endpoint, 'del_%s' % endpoint[1:], multi_decorators(decorators)(self._del(cls, serialize)), methods=[method, ])
        elif method == 'PUT':
            parameters = getConstraint(cls)
            if endpoint is None:
                endpoint = '%s/%s/%s' % (self._url_prefix, cls.__name__.lower(), unique_endpoint(cls))
            self.add_url_rule(endpoint, 'put_%s' % endpoint[1:], multi_decorators(decorators)(self._put(cls, serialize)), methods=[method, ])
        elif method == 'PATCH':
            parameters = getConstraint(cls)
            if endpoint is None:
                endpoint = '%s/%s/%s' % (self._url_prefix, cls.__name__.lower(), unique_endpoint(cls))
            self.add_url_rule(endpoint, 'patch_%s' % endpoint[1:], multi_decorators(decorators)(self._patch(cls, serialize)), methods=[method, ])
        logging.getLogger("werkzeug").info(" * add url rule %s for %s" % (endpoint, method))
        if endpoint.startswith(self._url_prefix):
            endpoint = endpoint[len(self._url_prefix):]
        if endpoint.split("/")[-1] == unique_endpoint(cls):
            endpoint = endpoint.split("/")[:-1] + ["{%s}" % endpoint.split("/")[-1].split(":")[1][:-1], ]
            endpoint = "/".join(endpoint)
        swagger = {"paths": {endpoint: {method.lower(): {"tags": [cls.__name__,], "summary": "", "description": "", "operationId": "%s_%s" % (cls.__name__.lower(), method), "parameters": []}}}}
        for column in parameters:
            parameter = {"name": column.name, "in": "path", "description": "", "required": True, "schema": {"type": SQLTYPE_TO_SWAGGERTYPE.get(column.type.__class__, 'string')}}
            swagger["paths"][endpoint][method.lower()]["parameters"].append(parameter)
        if method in ('POST', 'PUT', 'PATCH'):
            swagger["paths"][endpoint][method.lower()]["requestBody"] = {"description": "", "content": requestBody(cls, _origin_method)}
        swagger["paths"][endpoint][method.lower()]["responses"] = {}
        swagger["paths"][endpoint][method.lower()]["responses"]["200"] = {"description": "Successful operation", "content": responseBody(cls, _origin_method)}
        swagger["paths"][endpoint][method.lower()]["responses"]["400"] = {"description": "Error operation"}
        return swagger

    def _all(self, cls, serialize):
        def fct():
            offset = request.args.get('offset', 0)
            limit = request.args.get('limit', 999)
            order_by = request.args.get('orderby', '')
            filter = request.args.get('filter', '')
            return [serialize(item) for item in cls.query.filter(text(filter)).order_by(text(order_by)).offset(offset).limit(limit).all()], 200
        return fct

    def _post(self, cls, serialize):
        def fct(**kws):
            dct = {key: request.form.get(key) for key in request.form}
            if len(dct) == 0:
                dct = json.loads(request.get_data())
            for col in [c.name for c in cls.__table__.columns if c.autoincrement is True]:
                if col in dct:
                    del dct[col]
            for col in [c.name for c in cls.__table__.columns if 'not create by api' in str(c.comment)]:
                if col in dct:
                    del dct[col]
            item = cls(**dct)
            self._db.session.add(item)
            self._db.session.commit()
            return serialize(item), 201
        return fct

    def _get(self, cls, serialize):
        def fct(**kws):
            item = self._db.one_or_404(self._db.select(cls).filter_by(**kws), description=f"{cls.__name__} with parameters {','.join(['%s:%s' % (kw, kws[kw]) for kw in kws])}.")
            return serialize(item), 200
        return fct

    def _del(self, cls, serialize):
        def fct(**kws):
            item = self._db.one_or_404(self._db.select(cls).filter_by(**kws), description=f"{cls.__name__} with parameters {','.join(['%s:%s' % (kw, kws[kw]) for kw in kws])}.")
            self._db.session.delete(item)
            self._db.session.commit()
            return {"code": 200, "message": "element remove with success", "instance": request.path}, 200
        return fct

    def _put(self, cls, serialize):
        def fct(**kws):
            item = self._db.one_or_404(self._db.select(cls).filter_by(**kws), description=f"{cls.__name__} with parameters {','.join(['%s:%s' % (kw, kws[kw]) for kw in kws])}.")
            dct = {key: request.form.get(key) for key in request.form}
            if len(dct) == 0:
                dct = json.loads(request.get_data())
            for key in kws:
                dct[key] = kws[key]
            for col in [c.name for c in item.__table__.columns if 'not update by api' not in str(c.comment)]:
                item.__setattr__(col, dct.get(col))
            self._db.session.commit()
            return serialize(item), 200
        return fct

    def _patch(self, cls, serialize):
        def fct(**kws):
            item = self._db.one_or_404(self._db.select(cls).filter_by(**kws), description=f"{cls.__name__} with parameters {','.join(['%s:%s' % (kw, kws[kw]) for kw in kws])}.")
            dct = {key: request.form.get(key) for key in request.form}
            if len(dct) == 0:
                dct = json.loads(request.get_data())
            for key in kws:
                dct[key] = kws[key]
            for col in [key for key in dct if key in item.__table__.columns and 'not update by api' not in str(item.__table__.columns[key].comment)]:
                item.__setattr__(col, dct.get(col))
            self._db.session.commit()
            return serialize(item), 200
        return fct

    def register(self, app, options):
        try:
            Blueprint.register(self, app, options)
        except Exception:
            app.logger.error("init ApiRest on register is failed")


class Swagger(dict):

    def __init__(self, **kwargs):
        self["openapi"] = "3.0.3"
        self["info"] = {"title": "Swagger", "version": "0.0.1", "description": ""}
        self["servers"] = [{"url": "http://127.0.0.1:5000/api/v1"}]
        self["paths"] = {}
        for elt in kwargs:
            self[elt] = kwargs[elt]

    @property
    def description(self):
        return self["info"]["description"]

    @description.setter
    def description(self, value):
        self["info"]["description"] = value

    @property
    def openapi(self):
        return self["openapi"]

    @openapi.setter
    def openapi(self, value):
        self["openapi"] = value

    @property
    def title(self):
        return self["info"]["title"]

    @title.setter
    def title(self, value):
        self["info"]["title"] = value

    @property
    def version(self):
        return self["info"]["version"]

    @version.setter
    def version(self, value):
        self["info"]["version"] = value

    @property
    def url(self):
        return self["servers"][0]['url']

    @url.setter
    def url(self, value):
        self["servers"][0]['url'] = value

    def addEndPoint(self, value):
        path = list(value["paths"].keys())[0]
        endpoint = list(value["paths"][path].keys())[0]
        if path in self["paths"]:
            self["paths"][path][endpoint] = value["paths"][path][endpoint]
        else:
            self["paths"][path] = value["paths"][path]
