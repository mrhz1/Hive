<div className='space-y-6'>
      {/* TITLE */}
      <div>
        <h1 className='text-2xl font-bold text-[rgb(var(--foreground))]'>
          {isEdit ? 'Edit User' : 'New User'}
        </h1>
      </div>

      {/* FORM BODY */}
      <form
        onSubmit={(e) => {
          void handleSubmit(onSubmit, (validationErrors) =>
            console.log('❌ Form Validation Failed:', validationErrors),
          )(e);
        }}
        className='space-y-6 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-6'
      >
        {/* BASIC FIELDS */}
        <div className='grid grid-cols-1 gap-6 sm:grid-cols-2'>
          <FormField label='First Name' error={errors.first_name?.message}>
            <Input {...register('first_name')} />
          </FormField>

          <FormField label='Last Name' error={errors.last_name?.message}>
            <Input {...register('last_name')} />
          </FormField>

          <FormField label='Email Address' error={errors.email?.message}>
            <Input type='email' {...register('email')} />
          </FormField>

          <FormField label='Account Password' error={errors.password?.message}>
            <Input
              type='password'
              placeholder={isEdit ? '•••••••• (Leave blank to keep current)' : ''}
              {...register('password', {
                setValueAs: (v) => (v === '' ? undefined : v),
              })}
            />
          </FormField>
        </div>

        {/* AUTHORIZATION & STATE MGMT MANAGEMENT */}
        <div className='grid grid-cols-1 gap-6 border-t border-[rgb(var(--border))] pt-6 sm:grid-cols-2'>
          {/* SECURITY ASSIGNMENT (DYNAMIC DRIVEN) */}
          <Can perform='user:role'>
            <FormField label='Assigned System Role' error={errors.role_id?.message}>
              <Select {...register('role_id')} defaultValue=''>
                <option value='' disabled>
                  Select a role...
                </option>
                {availableRoles.map((role) => (
                  <option key={role.id} value={role.id}>
                    {role.name}
                  </option>
                ))}
              </Select>
            </FormField>
          </Can>

          {/* STATUS SELECTION */}
          <FormField label='Account Operational Status' error={errors.status?.message}>
            <Select {...register('status')} defaultValue=''>
              <option value='' disabled>
                Select a status...
              </option>
              {USER_STATUS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </FormField>
        </div>

        {/* FORM PANEL FORM CONTROLS ACTIONS */}
        <div className='flex justify-end border-t border-[rgb(var(--border))] pt-6'>
          <Button type='submit' disabled={isSubmitting}>
            {isSubmitting ? 'Saving Parameters...' : 'Save User'}
          </Button>
        </div>
      </form>
    </div>
