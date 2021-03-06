import math
import re

from wtforms import fields, widgets
from flask import request, url_for, redirect, flash, abort

from flask_superadmin.babel import gettext
from flask_superadmin.base import BaseView, expose
# from flask_superadmin.form import format_form
from flask_superadmin.form import BaseForm, ChosenSelectWidget, DatePickerWidget, \
    DateTimePickerWidget, FileField

import traceback

class AdminModelConverter(object):
    def convert(self, *args, **kwargs):
        field = super(AdminModelConverter, self).convert(*args, **kwargs)
        if field:
            widget = field.kwargs.get('widget', field.field_class.widget)
            # print field, widget
            if isinstance(widget, widgets.Select):
                field.kwargs['widget'] = ChosenSelectWidget(multiple=widget.multiple)
            elif issubclass(field.field_class, fields.DateTimeField):
                field.kwargs['widget'] = DateTimePickerWidget()
            elif issubclass(field.field_class, fields.DateField):
                field.kwargs['widget'] = DatePickerWidget()
            elif issubclass(field.field_class, fields.FileField):
                field.field_class = FileField
        return field


first_cap_re = re.compile('(.)([A-Z][a-z]+)')
def camelcase_to_space(name):
    return first_cap_re.sub(r'\1 \2', name)


def prettify(str):
    return str.replace('_', ' ').title()


class BaseModelAdmin(BaseView):
    """
    BaseModelView provides create/edit/delete functionality for a peewee Model.
    """

    # Number of objects to display per page in the list view
    list_per_page = 20

    # Columns to display in the list index - can be field names or callables.
    # Admin's methods have higher priority than the fields/methods on
    # the model or document.
    list_display = tuple()

    # form parameters, lists of fields
    exclude = None
    only = None
    fields = None
    readonly_fields = []
    fields_order = None  # order of the fields in the form. Fields that aren't mentioned here are appended at the end

    form = None

    can_edit = True
    can_create = True
    can_delete = True

    list_template = 'admin/model/list.html'
    edit_template = 'admin/model/edit.html'
    add_template = 'admin/model/add.html'
    delete_template = 'admin/model/delete.html'

    search_fields = None
    actions = None

    field_overrides = {}

    # a dictionary of field_name: overridden_params_dict, e.g.
    # { 'first_name': { 'label': 'First', 'description': 'This is first name' } }
    # parameters that can be overridden: label, description, validators, filters, default
    field_args = None

    @staticmethod
    def model_detect(model):
        return False

    def __init__(self, model=None, name=None, category=None, endpoint=None,
                 url=None):
        if name is None:
            name = '%s' % camelcase_to_space(model.__name__)

        if endpoint is None:
            endpoint = ('%s' % model.__name__).lower()

        super(BaseModelAdmin, self).__init__(name, category, endpoint, url)

        if model:
            self.model = model

    def get_display_name(self):
        return self.model.__name__

    def allow_pk(self):
        return not self.model._meta.auto_increment

    def get_column(self, instance, name):
        parts = name.split('.')
        value = instance
        for p in parts:

            # admin's methods have higher priority than the fields/methods on
            # the model or document. If a callable is found on the admin
            # level, it's also passed an instance object
            if hasattr(self, p) and callable(getattr(self, p)):
                value = getattr(self, p)(instance)
            else:
                value = getattr(value, p, None)
                if callable(value):
                    value = value()

            if not value:
                break

        return value

    def get_reference(self, column_value):
        for model, model_view in self.admin._models:
            if type(column_value) == model:
                return '/admin/%s/%s/' % (model_view.endpoint, column_value.pk)

    def get_converter(self):
        raise NotImplemented()

    def get_model_form(self):
        """ Returns the model form, should get overridden in backend-specific
        view.
        """
        raise NotImplemented()

    def get_form(self, include_readonly=False):
        if include_readonly:
            exclude = self.exclude
        else:
            exclude = list(set(self.exclude or []) | set(self.readonly_fields or []))

        only = list(set(self.only or []) - set(exclude or []))

        model_form = self.get_model_form()
        converter = self.get_converter()
        if isinstance(converter, type):
            converter = converter()
        form = model_form(self.model, base_class=BaseForm, only=only,
                          exclude=exclude, field_args=self.field_args,
                          converter=converter, fields_order=self.fields_order)

        form.readonly_fields = self.readonly_fields
        return form

    def get_add_form(self):
        return self.get_form()

    def get_objects(self, *pks):
        raise NotImplemented()

    def get_object(self, pk):
        raise NotImplemented()

    def get_pk(self, instance):
        return

    def save_model(self, instance, form, adding=False):
        raise NotImplemented()

    def delete_models(self, *pks):
        raise NotImplemented()

    def is_sortable(self, column):
        return False

    def field_name(self, field):
        return prettify(field)

    def construct_search(self, field_name):
        raise NotImplemented()

    def get_queryset(self):
        raise NotImplemented()

    def get_list(self):
        raise NotImplemented()

    def get_url_name(self, name):
        URLS = {
            'index': '.list',
            'add': '.add',
            'delete': '.delete',
            'edit': '.edit'
        }
        return URLS[name]

    def dispatch_save_redirect(self, instance):
        if '_edit' in request.form:
            return redirect(
                url_for(self.get_url_name('edit'), pk=self.get_pk(instance))
            )
        elif '_add_another' in request.form:
            return redirect(url_for(self.get_url_name('add')))
        else:
            return redirect(url_for(self.get_url_name('index')))

    @expose('/add/', methods=('GET', 'POST'))
    def add(self):
        Form = self.get_add_form()
        if request.method == 'POST':
            form = Form()
            if form.validate_on_submit():
                try:
                    instance = self.save_model(self.model(), form, True)
                    flash(gettext('New %(model)s saved successfully',
                          model=self.get_display_name()), 'success')
                    return self.dispatch_save_redirect(instance)
                except Exception, ex:
                    print traceback.format_exc()
                    try:
                        if self.session:
                            self.session.rollback()
                    except AttributeError:
                        pass
                    flash(gettext('Failed to add model. %(error)s',
                          error=str(ex)), 'error')

        else:
            form = Form(obj=self.model())

        return self.render(self.add_template, model=self.model, form=form)

    @property
    def page(self):
        return request.args.get('page', 0, type=int)

    def total_pages(self, count):
        return int(math.ceil(float(count) / self.list_per_page))

    @property
    def sort(self):
        sort = request.args.get('sort', None)
        if sort and sort.startswith('-'):
            desc = True
            sort = sort[1:]
        else:
            desc = False
        return sort, desc

    @property
    def search(self):
        return request.args.get('q', None)

    def page_url(self, page):
        search_query = self.search
        sort, desc = self.sort
        if sort and desc:
            sort = '-' + sort
        if page == 0:
            page = None
        return url_for(self.get_url_name('index'), page=page, sort=sort, q=search_query)

    def sort_url(self, sort, desc=None):
        if sort and desc:
            sort = '-' + sort
        search_query = self.search
        return url_for(self.get_url_name('index'), sort=sort, q=search_query)

    @expose('/', methods=('GET', 'POST',))
    def list(self):
        """
            List view
        """
        # Grab parameters from URL
        if request.method == 'POST':
            id_list = request.form.getlist('_selected_action')
            if id_list and (request.form.get('action-delete') or \
                request.form.get('action', None) == 'delete'):
                return self.delete(*id_list)

        sort, sort_desc = self.sort
        page = self.page
        search_query = self.search
        count, data = self.get_list(page=page, sort=sort, sort_desc=sort_desc,
                                    search_query=search_query)

        return self.render(self.list_template, data=data, page=page,
                           total_pages=self.total_pages(count), sort=sort,
                           sort_desc=sort_desc, count=count, modeladmin=self,
                           search_query=search_query)

    @expose('/<pk>/', methods=('GET', 'POST'))
    def edit(self, pk):
        try:
            instance = self.get_object(pk)
        except self.model.DoesNotExist:
            abort(404)

        Form = self.get_form(include_readonly=request.method == 'GET')

        if request.method == 'POST':
            form = Form(obj=instance)
            if form.validate_on_submit():
                try:
                    self.save_model(instance, form, False)
                    flash('Changes to %s saved successfully' % self.get_display_name(),
                          'success')
                    return self.dispatch_save_redirect(instance)
                except Exception, ex:
                    print traceback.format_exc()
                    flash(gettext('Failed to edit model. %(error)s', error=str(ex)),
                          'error')
        else:
            form = Form(obj=instance)

        return self.render(self.edit_template, model=self.model, form=form,
                           pk=self.get_pk(instance), instance=instance)

    @expose('/<pk>/delete', methods=('GET', 'POST'))
    def delete(self, pk=None, *pks):
        if pk:
            pks += pk,
            # collected = {}
            # if self.delete_collect_objects:
            #     for obj in query:
            #         collected[obj.get_pk()] = self.collect_objects(obj)

        if request.method == 'POST' and 'confirm_delete' in request.form:
            count = len(pks)
            self.delete_models(*pks)

            flash('Successfully deleted %s %ss' % (count, self.get_display_name()),
                  'success')
            return redirect(url_for(self.get_url_name('index')))
        else:
            instances = self.get_objects(*pks)

        return self.render(self.delete_template,
            instances=instances
            # query=query,
            # collected=collected,
        )


class ModelAdmin(object): pass
